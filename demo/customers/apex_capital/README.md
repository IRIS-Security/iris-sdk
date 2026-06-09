# Apex Capital — Greenfield Financial Services Demo

Fictional fintech customer with deliberately ungoverned loan-processing agents.
Used in the IRIS SE demo to show discovery, registration, and governance.

## Agents

| File | Status | Purpose |
|---|---|---|
| `loan_processor.py` | Ungoverned | LangChain loan agent — triggers IRIS scan findings |
| `fraud_detector.py` | Ungoverned | OpenAI fraud agent — no audit trail |
| `governed_loan.py` | Governed | Same agent after IRIS governance applied |

## Demo usage

```bash
iris scan --dir demo/customers/apex_capital --discover
```
