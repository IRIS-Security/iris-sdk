"""
Validates and manages the IRIS license key.

All validation is local — no network calls.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from iris_core.entitlements.features import Tier

KEY_PATTERN = re.compile(r"^IRIS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
ENV_LICENSE_KEY = "IRIS_LICENSE_KEY"

TEST_KEYS = {
    "IRIS-TEST-0000-0000-0001": Tier.PRO,
    "IRIS-TEST-0000-0000-0002": Tier.ENTERPRISE,
    "IRIS-DEMO-0000-0000-0001": Tier.PRO,
}


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

        prefix = key[5]  # character after "IRIS-"
        if prefix == "P":
            return True, Tier.PRO, "valid"
        if prefix == "E":
            return True, Tier.ENTERPRISE, "valid"
        if prefix == "F":
            return True, Tier.FREE, "valid"

        return False, Tier.FREE, "invalid_tier_encoding"

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
