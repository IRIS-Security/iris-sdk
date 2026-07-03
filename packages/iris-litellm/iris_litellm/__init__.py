"""
IRIS LiteLLM integration — derive compliance workload profiles from LiteLLM.

OSS/PAID CLASSIFICATION (P59):
  READ logic (LiteLLM config/proxy -> WorkloadProfile) -> OSS. Adoption hook.
  profile_from_litellm_*() returning dict to caller     -> OSS.
  push_profile() POST /intelligence/profile/scan         -> OSS client; endpoint
      gated cloud-side by compliance_full_eval (402 if unentitled).
  Continuous monitoring / drift / historical trends /
  posture-over-time / evidence mapping                   -> PAID, CLOUD ONLY.
      This package takes a point-in-time snapshot and stops.

Keep your LiteLLM router. IRIS reads what you're running and tells you which
regulations apply — with tamper-evident proof.
"""

from __future__ import annotations

from iris_litellm.config_reader import profile_from_litellm_config
from iris_litellm.proxy_reader import IrisLiteLLM, profile_from_litellm_proxy

__version__ = "0.1.0"

__all__ = [
    "IrisLiteLLM",
    "profile_from_litellm_config",
    "profile_from_litellm_proxy",
]
