"""
Validates and manages the IRIS license key.

All validation is local — no network calls.

Public git clones ship with no embedded salt and dev keys disabled.
Production salt is injected at PyPI release build time only (see
scripts/inject_license_salt.py). Maintainers may also set
IRIS_LICENSE_SALT locally for key generation/testing.
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
ENV_LICENSE_SALT = "IRIS_LICENSE_SALT"
ENV_ALLOW_DEV_LICENSE_KEYS = "IRIS_ALLOW_DEV_LICENSE_KEYS"

# Injected at publish via scripts/inject_license_salt.py — never commit a real value.
_LICENSE_SALT = ""

KNOWN_INSECURE_SALTS = frozenset(
    {
        "",
        "CHANGE-THIS-TO-SOMETHING-ONLY-YOU-KNOW",
        "test-only-salt-not-published",
    }
)

TIER_FROM_PREFIX = {
    "P": Tier.PRO,
    "E": Tier.ENTERPRISE,
    "D": Tier.PRO,
    "T": Tier.PRO,
    "F": Tier.FREE,
}

# Dev-only keys — rejected unless IRIS_ALLOW_DEV_LICENSE_KEYS=1 (CI/tests only).
TEST_KEYS = {
    "IRIS-TEST-0000-0000-0001": Tier.PRO,
    "IRIS-TEST-0000-0000-0002": Tier.ENTERPRISE,
    "IRIS-DEMO-0000-0000-0001": Tier.PRO,
}


def _effective_salt() -> str:
    if _LICENSE_SALT and _LICENSE_SALT not in KNOWN_INSECURE_SALTS:
        return _LICENSE_SALT
    return os.environ.get(ENV_LICENSE_SALT, "").strip()


def _dev_keys_allowed() -> bool:
    return os.environ.get(ENV_ALLOW_DEV_LICENSE_KEYS, "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _compute_checksum(seg1: str, seg2: str, seg3: str, salt: str) -> str:
    payload = f"{seg1}{seg2}{seg3}{salt}"
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
            if _dev_keys_allowed():
                return True, TEST_KEYS[key], "valid"
            return False, Tier.FREE, "dev_key_disabled"

        salt = _effective_salt()
        if not salt or salt in KNOWN_INSECURE_SALTS:
            return False, Tier.FREE, "invalid_checksum"

        parts = key.split("-")
        seg1, seg2, seg3, checksum = parts[1], parts[2], parts[3], parts[4]
        expected = _compute_checksum(seg1, seg2, seg3, salt)
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
