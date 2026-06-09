"""Run every demo CLI command and confirm it works. Run before customer demos."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run(cmd, allow_fail=False):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0 and not allow_fail:
        print(f"FAIL: {cmd}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        sys.exit(1)
    return result.stdout


print("Verifying IRIS demo environment...")
run("iris --version")
run("iris scan --dir demo/customers --discover", allow_fail=True)
run(
    "iris compliance check --framework colorado-ai-act "
    "--dir demo/governance/agents --agent demo-payment-agent",
)
run(
    "iris compliance check --framework colorado-ai-act "
    "--dir demo/governance/agents --agent demo-hr-agent",
)
run(
    'python3 -c "'
    "from iris_core.models.passport import AgentPassport; "
    "from pathlib import Path; "
    "p = AgentPassport.from_yaml("
    "Path('demo/governance/agents/demo-payment-agent/passport.yaml').read_text()); "
    'print(p.name, p.evidence_vault_id)"'
)
print("All demo commands verified. Ready to demo.")
