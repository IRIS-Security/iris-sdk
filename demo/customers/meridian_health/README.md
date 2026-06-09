# Meridian Health — Brownfield Healthcare Demo

Fictional healthcare customer with ungoverned PHI-accessing agents.
Used in the IRIS SE demo to show HIPAA-relevant risk and governance.

## Agents

| File | Status | Purpose |
|---|---|---|
| `patient_summarizer.py` | Ungoverned | Anthropic agent accessing PHI |
| `appointment_scheduler.py` | Ungoverned | LangChain scheduling agent |
| `governed_patient.py` | Governed | Same agent after IRIS governance applied |

## Demo usage

```bash
iris scan --dir demo/customers/meridian_health --discover
```
