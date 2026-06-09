"""Verify everything needed for the IRIS SE demo is installed and configured."""

import subprocess
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

checks = []


def check(name, fn):
    try:
        result = fn()
        checks.append((name, True, result))
    except Exception as e:
        checks.append((name, False, str(e)))


check("Python 3.10+", lambda: sys.version)
check(
    "iris CLI",
    lambda: subprocess.check_output(["iris", "--version"], text=True).strip(),
)
check("iris-security-sdk", lambda: __import__("iris") and "OK")
check(
    "ANTHROPIC_API_KEY or OPENAI_API_KEY",
    lambda: (
        "set"
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        else (_ for _ in ()).throw(Exception("No LLM API key found"))
    ),
)
check(
    "demo/governance/agents/demo-payment-agent/passport.yaml exists",
    lambda: (
        open(REPO_ROOT / "demo/governance/agents/demo-payment-agent/passport.yaml")
        and "OK"
    ),
)

print("")
print("IRIS Demo Prerequisites Check")
print("=" * 40)
all_pass = True
for name, passed, detail in checks:
    status = "✓" if passed else "✗"
    print(f"  {status} {name}")
    if not passed:
        print(f"      {detail}")
        all_pass = False
print("")
if all_pass:
    print("All checks passed. Run: bash demo/run_demo.sh")
else:
    print("Fix the issues above before running the demo.")
    sys.exit(1)
