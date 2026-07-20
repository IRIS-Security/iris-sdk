"""
IRIS AGT integration — derive compliance workload profiles from Microsoft AGT
(agent-governance-toolkit) audit trails.

OSS/PAID CLASSIFICATION (P59):
  READ logic (AGT audit trail -> WorkloadProfile)     -> OSS. Adoption hook.
  profile_from_agt() returning dict to caller         -> OSS.
  push_profile() POST /intelligence/profile/scan      -> OSS client; endpoint
      gated cloud-side by compliance_full_eval (402 if unentitled).
  Continuous monitoring / drift / historical trends /
  posture-over-time / evidence mapping                  -> PAID, CLOUD ONLY.
      This package takes a point-in-time snapshot and stops.

Already running AGT for policy enforcement, sandboxing, and Merkle-chained
audit? Keep it. IRIS reads AGT's own audit-trail export and tells you which
regulations apply — with tamper-evident proof AGT's own docs say to get
from elsewhere ("engage qualified legal counsel and notified bodies for
formal compliance evaluation" — AGT's EU AI Act checklist).
"""

from __future__ import annotations

from iris_agt.reader import parse_agt_audit_trail, profile_from_agt, verify_chain_continuity

__version__ = "0.1.0"

__all__ = [
    "parse_agt_audit_trail",
    "profile_from_agt",
    "verify_chain_continuity",
]
