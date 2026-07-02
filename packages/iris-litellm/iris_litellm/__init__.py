"""
IRIS LiteLLM integration — derive compliance workload profiles from LiteLLM.

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
