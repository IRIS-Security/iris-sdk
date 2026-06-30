# IRIS MCP Server

Connect IRIS to Claude Desktop or Cursor and ask Claude to govern your AI agents in plain English.

## Install

```bash
pip install iris-security-mcp
# or as an SDK extra:
pip install "iris-security-sdk[mcp]"
```

## Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "iris-governance": {
      "command": "iris-mcp",
      "args": [],
      "env": {
        "IRIS_LICENSE_KEY": "your-iris-license-key",
        "IRIS_GOVERNANCE_DIR": "/path/to/your/governance"
      }
    }
  }
}
```

Restart Claude Desktop. IRIS tools will appear in Claude's tool panel.

## Connect to Cursor

Add to your project `.cursor/mcp.json` or Cursor MCP settings:

```json
{
  "mcpServers": {
    "iris-governance": {
      "command": "iris-mcp",
      "args": ["--cursor-mode"],
      "env": {
        "IRIS_LICENSE_KEY": "${env:IRIS_LICENSE_KEY}",
        "IRIS_GOVERNANCE_DIR": "${workspaceFolder}/governance"
      }
    }
  }
}
```

## What you can ask Claude

**"What AI agents exist in my codebase?"**
→ Claude calls `iris_scan_discover` and shows findings

**"Which regulations apply to my loan processing agent?"**
→ Claude calls `iris_framework_suggest` with context

**"Check if my agent is compliant with the Colorado AI Act"**
→ Claude calls `iris_compliance_check` and explains each rule

**"Register a new agent called customer-support"**
→ Claude calls `iris_declare` and walks through the wizard

**"I have a pending HITL review — show me what needs approval"**
→ Claude calls `iris_hitl_list` and shows pending reviews

**"Approve review rev_a3f9c12e"**
→ Claude calls `iris_hitl_approve`

**"How much is my payment agent costing in LLM tokens?"**
→ Claude calls `iris_cost_report` (Pro)

## Free vs Pro tools

Free tools work without a license key. Pro tools require `iris license activate <your-key>`.

Run:

```bash
iris license status
```

to see your current tier and available tools.

## List tools locally

```bash
iris-mcp --help
iris-mcp --list-tools    # 20+ governance tools
iris-mcp --version
```

Tools include discovery (`iris_scan_discover`), compliance (`iris_compliance_check`, `iris_certify`), regulatory intelligence (`iris_regulatory_check`), HITL (`iris_hitl_list`, `iris_hitl_approve`), cost tracking (Pro), and framework suggestion.
