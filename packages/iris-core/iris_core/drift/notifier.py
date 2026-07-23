"""Drift alert delivery — Slack, webhook, email, and breach notifications."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml

from iris_core.drift.detector import DriftDetector, DriftReport
from iris_core.entitlements import Entitlements, Feature

ALERT_CONFIG_PATH = Path.home() / ".iris" / "alert-config.yaml"
SIGNATURE_HEADER = "X-IRIS-Signature"


def load_alert_config() -> dict[str, Any]:
    if ALERT_CONFIG_PATH.exists():
        data = yaml.safe_load(ALERT_CONFIG_PATH.read_text()) or {}
        if isinstance(data, dict):
            return data
    return {}


def save_alert_config(config: dict[str, Any]) -> Path:
    ALERT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return ALERT_CONFIG_PATH


def _sign_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


@dataclass
class BreachNotification:
    """HIPAA/GDPR breach notification payload for external alerting."""

    breach_id: str
    agent_name: str
    phi_patterns_detected: List[str]
    detected_at: str
    iris_rule: str
    notification_window: str = "72 hours (GDPR) / 60 days (HIPAA)"
    severity: str = "CRITICAL"
    gdpr_window: Optional[str] = None
    hipaa_window: Optional[str] = None


class DriftNotifier:
    """Sends drift alerts to external channels."""

    def notify_slack(self, webhook_url: str, report: DriftReport) -> bool:
        if not report.has_degradation():
            return False

        detector = DriftDetector(Path.cwd())
        message = detector.generate_alert(report)
        if not message:
            return False

        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": "IRIS Compliance Drift Alert"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Your AI governance posture degraded since the last snapshot.*",
                },
            },
        ]

        if report.new_violations:
            violation_lines = []
            for event in report.new_violations:
                violation_lines.append(
                    f"*[ {event.severity} ]* `{event.agent_name}`: {event.rule_id}\n"
                    f"_{event.description}_\n"
                    f"Likely cause: {event.likely_cause}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{len(report.new_violations)} new violation(s):*\n"
                        + "\n".join(violation_lines),
                    },
                }
            )

        if report.production_ready_lost:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Production readiness lost:*\n"
                        + "\n".join(f"• `{name}`" for name in report.production_ready_lost),
                    },
                }
            )

        degraded = [s for s in report.score_changes if s.direction == "degraded"]
        if degraded:
            score_text = "\n".join(
                f"• {s.framework}: {int(s.previous_score * 100)}% → {int(s.current_score * 100)}% "
                f"({int(s.delta * 100):+d}%)"
                for s in degraded
            )
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Score changes:*\n{score_text}"}}
            )

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Run `iris status` · `iris compliance check --framework colorado-ai-act`",
                    }
                ],
            }
        )

        payload = json.dumps({"text": message.split("\n")[0], "blocks": blocks}).encode("utf-8")
        request = Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                return 200 <= response.status < 300
        except (URLError, OSError):
            return False

    def notify_webhook(self, url: str, report: DriftReport) -> bool:
        payload = json.dumps(report.to_dict(), separators=(",", ":")).encode("utf-8")
        config = load_alert_config()
        secret = (
            config.get("webhook_secret")
            or os.environ.get("IRIS_WEBHOOK_SECRET")
            or "iris-drift"
        )
        signature = _sign_payload(payload, secret)
        request = Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: signature,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                return 200 <= response.status < 300
        except (URLError, OSError):
            return False

    def notify_email(self, address: str, report: DriftReport) -> bool:
        detector = DriftDetector(Path.cwd())
        body = detector.generate_alert(report)
        if not body:
            return False

        config = load_alert_config()
        smtp_cfg = config.get("smtp") or {}
        host = smtp_cfg.get("host") or os.environ.get("IRIS_SMTP_HOST")
        port = int(smtp_cfg.get("port") or os.environ.get("IRIS_SMTP_PORT") or 587)
        user = smtp_cfg.get("user") or os.environ.get("IRIS_SMTP_USER")
        password = smtp_cfg.get("password") or os.environ.get("IRIS_SMTP_PASS")

        if not host:
            return False

        msg = EmailMessage()
        msg["Subject"] = "IRIS Compliance Drift Alert"
        msg["From"] = user or "iris@localhost"
        msg["To"] = address
        msg.set_content(body)

        try:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if user and password:
                    server.starttls()
                    server.login(user, password)
                server.send_message(msg)
            return True
        except (OSError, smtplib.SMTPException):
            return False

    def notify_breach(
        self,
        breach: BreachNotification,
        webhook_url: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """
        Send a breach notification when CRITICAL PHI/PII was exposed and not blocked.

        Requires Feature.DRIFT_WEBHOOK_ALERT or DRIFT_EMAIL_ALERT (Pro).
        Free tier logs breach indicators to the Evidence Vault only.
        """
        ents = Entitlements()
        can_webhook = ents.has(Feature.DRIFT_WEBHOOK_ALERT)
        can_email = ents.has(Feature.DRIFT_EMAIL_ALERT)
        if not can_webhook and not can_email:
            return False

        config = load_alert_config()
        webhook_url = webhook_url or config.get("webhook_url")
        email = email or config.get("email")

        payload_dict = {
            "event": "potential_data_breach",
            "breach_id": breach.breach_id,
            "agent_name": breach.agent_name,
            "phi_patterns": breach.phi_patterns_detected,
            "detected_at": breach.detected_at,
            "notification_window": breach.notification_window,
            "iris_rule": breach.iris_rule,
            "severity": breach.severity,
            "gdpr_window": breach.gdpr_window,
            "hipaa_window": breach.hipaa_window,
        }
        payload = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
        sent = False

        if webhook_url and can_webhook:
            secret = (
                config.get("webhook_secret")
                or os.environ.get("IRIS_WEBHOOK_SECRET")
                or "iris-drift"
            )
            signature = _sign_payload(payload, secret)
            request = Request(
                webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: signature,
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=15) as response:
                    sent = sent or (200 <= response.status < 300)
            except (URLError, OSError):
                pass

        if email and can_email:
            smtp_cfg = config.get("smtp") or {}
            host = smtp_cfg.get("host") or os.environ.get("IRIS_SMTP_HOST")
            port = int(smtp_cfg.get("port") or os.environ.get("IRIS_SMTP_PORT") or 587)
            user = smtp_cfg.get("user") or os.environ.get("IRIS_SMTP_USER")
            password = smtp_cfg.get("password") or os.environ.get("IRIS_SMTP_PASS")
            if host:
                patterns = ", ".join(breach.phi_patterns_detected) or "unknown"
                body = (
                    f"IRIS POTENTIAL DATA BREACH — {breach.severity}\n\n"
                    f"Breach ID: {breach.breach_id}\n"
                    f"Agent: {breach.agent_name}\n"
                    f"Detected: {breach.detected_at}\n"
                    f"Patterns: {patterns}\n"
                    f"Rule: {breach.iris_rule}\n"
                    f"GDPR notification deadline: {breach.gdpr_window}\n"
                    f"HIPAA notification deadline: {breach.hipaa_window}\n"
                    f"Notification window: {breach.notification_window}\n"
                )
                msg = EmailMessage()
                msg["Subject"] = f"IRIS Breach Alert — {breach.agent_name}"
                msg["From"] = user or "iris@localhost"
                msg["To"] = email
                msg.set_content(body)
                try:
                    with smtplib.SMTP(host, port, timeout=15) as server:
                        if user and password:
                            server.starttls()
                            server.login(user, password)
                        server.send_message(msg)
                    sent = True
                except (OSError, smtplib.SMTPException):
                    pass

        return sent
