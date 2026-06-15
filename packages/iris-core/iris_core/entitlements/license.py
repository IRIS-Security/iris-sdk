"""
Validates and manages the IRIS license key.

All validation is local — no network calls.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from iris_core.entitlements.features import Tier

KEY_PATTERN = re.compile(r"^IRIS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
ENV_LICENSE_KEY = "IRIS_LICENSE_KEY"

# Must match tools/licensing/config.py SECRET_SALT. Rotate both together.
SDK_SECRET_SALT = "CHANGE-THIS-TO-SOMETHING-ONLY-YOU-KNOW"

TIER_FROM_PREFIX = {
    "P": Tier.PRO,
    "E": Tier.ENTERPRISE,
    "D": Tier.PRO,
    "T": Tier.PRO,
    "F": Tier.FREE,
}

TEST_KEYS = {
    "IRIS-TEST-0000-0000-0001": Tier.PRO,
    "IRIS-TEST-0000-0000-0002": Tier.ENTERPRISE,
    "IRIS-DEMO-0000-0000-0001": Tier.PRO,
}

# Deterministic keys for unit tests (valid checksum with SDK_SECRET_SALT).
SAMPLE_LICENSE_KEYS = {
    "pro": "IRIS-P123-ABCD-EFGH-7EA1",
    "enterprise": "IRIS-E123-ABCD-EFGH-FA7C",
    "free": "IRIS-F123-ABCD-EFGH-D823",
}


def _compute_checksum(seg1: str, seg2: str, seg3: str) -> str:
    payload = f"{seg1}{seg2}{seg3}{SDK_SECRET_SALT}"
    return hashlib.sha256(payload.encode()).hexdigest()[:4].upper()


def _tier_from_prefix(prefix: str) -> Optional[Tier]:
    return TIER_FROM_PREFIX.get(prefix)


class LicenseKey:
    """Validates and manages the IRIS license key (offline only)."""

    @staticmethod
    def license_file_path() -> Path:
        return Path.home() / ".iris" / "license.key"

    @staticmethod
    def validate(key: str) -> Tuple[bool, Tier, str]:
        """Return (is_valid, tier, reason)."""
        key = key.strip()
        if not KEY_PATTERN.match(key):
            return False, Tier.FREE, "invalid_format"

        if key in TEST_KEYS:
            return True, TEST_KEYS[key], "valid"

        parts = key.split("-")
        seg1, seg2, seg3, checksum = parts[1], parts[2], parts[3], parts[4]
        expected = _compute_checksum(seg1, seg2, seg3)
        if checksum != expected:
            return False, Tier.FREE, "invalid_checksum"

        tier = _tier_from_prefix(seg1[0])
        if tier is None:
            return False, Tier.FREE, "invalid_tier_encoding"

        return True, tier, "valid"

    @staticmethod
    def save(key: str) -> bool:
        """Save key to ~/.iris/license.key."""
        path = LicenseKey.license_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key.strip())
        return True

    @staticmethod
    def load() -> Optional[str]:
        """Read from ~/.iris/license.key. Returns None if not found."""
        path = LicenseKey.license_file_path()
        if path.exists():
            return path.read_text().strip()
        return None

    @staticmethod
    def clear() -> bool:
        """Remove ~/.iris/license.key."""
        path = LicenseKey.license_file_path()
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def read_active_key() -> Optional[str]:
        """Read license key from env (priority) or disk."""
        env_key = os.environ.get(ENV_LICENSE_KEY, "").strip()
        if env_key:
            return env_key
        return LicenseKey.load()
