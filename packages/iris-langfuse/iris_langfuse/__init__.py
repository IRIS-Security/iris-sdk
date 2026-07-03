"""
IRIS Langfuse integration — derive compliance workload profiles from Langfuse traces.

OSS/PAID CLASSIFICATION (P59):
  READ logic (Langfuse -> WorkloadProfile)           -> OSS. Adoption hook.
  profile_from_langfuse() returning dict to caller   -> OSS.
  push_profile() POST /intelligence/profile/scan     -> OSS client; endpoint
      gated cloud-side by compliance_full_eval (402 if unentitled).
  Continuous monitoring / drift / historical trends /
  posture-over-time / evidence mapping                 -> PAID, CLOUD ONLY.
      This package takes a point-in-time snapshot and stops.

Keep your Langfuse setup. IRIS reads what you're running and tells you which
regulations apply — with tamper-evident proof.
"""

from __future__ import annotations

from iris_langfuse.reader import IrisLangfuse, profile_from_langfuse

__version__ = "0.1.0"

__all__ = [
    "IrisLangfuse",
    "profile_from_langfuse",
]
