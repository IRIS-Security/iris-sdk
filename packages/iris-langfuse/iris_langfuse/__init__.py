"""
IRIS Langfuse integration — derive compliance workload profiles from Langfuse traces.

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
