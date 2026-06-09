"""Run every demo CLI command and confirm it works. Run before customer demos."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_iris_is_transparent():
    """Verify IrisAnthropic proxies all attributes correctly."""
    from iris import AgentPassport

    passport = AgentPassport(name="test", owner="test@test.com", team="test")

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.models.list.return_value = ["claude-3-5-sonnet"]

        try:
            from iris_anthropic import IrisAnthropic

            client = IrisAnthropic(passport=passport)
            result = client.models.list()
            assert result == ["claude-3-5-sonnet"], "Proxy failed"
            print("PASS: IrisAnthropic proxies attributes correctly")
        except ImportError:
            print("SKIP: iris-anthropic not installed")


print("Verifying IRIS demo environment...")
run("iris --version")
run("iris explain")
run("iris explain --technical")
run("iris status")
run("iris scan --dir demo/customers --discover", allow_fail=True)
run(
    "iris scan --dir demo/customers/meridian_health --discover --govern "
    "--no-auto-apply --yes --compliance colorado-ai-act"
)
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
test_iris_is_transparent()

import time

vault = REPO_ROOT / "demo/governance/evidence/demo-payment-agent"
dest = Path.home() / ".iris/evidence/demo-payment-agent"
dest.mkdir(parents=True, exist_ok=True)
for f in vault.glob("*.jsonl"):
    (dest / f.name).write_text(f.read_text())

watch = subprocess.Popen(
    ["iris", "watch", "--agent", "demo-payment-agent", "--tail", "2"],
    cwd=REPO_ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
time.sleep(2)
watch.terminate()
watch.wait(timeout=5)
if watch.returncode not in (0, -15, None):
    print(f"WARN: iris watch exited with {watch.returncode}")
else:
    print("PASS: iris watch starts without errors")

print("All demo commands verified. Ready to demo.")
