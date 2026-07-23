"""
Model Capability Registry — first-class governance for LLM tiers and export controls.

Runs fully local: load from governance/models/registry.yaml in your repo, or use
the bundled defaults shipped with iris-core. No hosted API required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import fnmatch
import yaml

from iris_core.models.governance_paths import find_governance_root


class ModelTier(str, Enum):
    STANDARD = "standard"
    FRONTIER = "frontier"
    FRONTIER_RESTRICTED = "frontier-restricted"


class ExportControlStatus(str, Enum):
    UNRESTRICTED = "unrestricted"
    BIS_RESTRICTED = "bis-restricted"
    GOVERNMENT_SUSPENDED = "government-suspended"


@dataclass
class ModelCapability:
    model_id: str
    provider: str = "unknown"
    tier: ModelTier = ModelTier.STANDARD
    capabilities: List[str] = field(default_factory=list)
    export_control: ExportControlStatus = ExportControlStatus.UNRESTRICTED
    retention_days: int = 0
    requires_hitl: bool = False
    allowed_work_authorizations: List[str] = field(default_factory=list)
    fallback_model: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, model_id: str, data: Dict[str, Any]) -> "ModelCapability":
        tier_raw = data.get("tier", "standard")
        export_raw = data.get("export_control", "unrestricted")
        return cls(
            model_id=model_id,
            provider=data.get("provider", "unknown"),
            tier=ModelTier(tier_raw),
            capabilities=list(data.get("capabilities", [])),
            export_control=ExportControlStatus(export_raw),
            retention_days=int(data.get("retention_days", 0)),
            requires_hitl=bool(data.get("requires_hitl", False)),
            allowed_work_authorizations=[
                str(v).lower() for v in data.get("allowed_work_authorizations", [])
            ],
            fallback_model=data.get("fallback_model"),
            aliases=[str(a) for a in data.get("aliases", [])],
        )

    def matches(self, model_id: str) -> bool:
        if model_id == self.model_id:
            return True
        return any(fnmatch.fnmatch(model_id, alias) for alias in self.aliases)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "tier": self.tier.value,
            "capabilities": self.capabilities,
            "export_control": self.export_control.value,
            "retention_days": self.retention_days,
            "requires_hitl": self.requires_hitl,
            "allowed_work_authorizations": self.allowed_work_authorizations,
            "fallback_model": self.fallback_model,
            "aliases": self.aliases,
        }


@dataclass
class ModelRegistry:
    """Local model capability registry — GitOps source of truth in governance/models/."""

    models: Dict[str, ModelCapability] = field(default_factory=dict)
    source_path: Optional[Path] = None

    def resolve(self, model_id: str) -> Optional[ModelCapability]:
        if not model_id:
            return None
        if model_id in self.models:
            return self.models[model_id]
        for capability in self.models.values():
            if capability.matches(model_id):
                return capability
        return None

    def list_models(self, *, tier: Optional[ModelTier] = None) -> List[ModelCapability]:
        items = list(self.models.values())
        if tier is not None:
            items = [m for m in items if m.tier == tier]
        return sorted(items, key=lambda m: (m.tier.value, m.model_id))

    @classmethod
    def load(cls, governance_root: Optional[Path] = None) -> "ModelRegistry":
        root = governance_root or find_governance_root()
        user_path = root / "models" / "registry.yaml"
        if user_path.exists():
            return cls.from_yaml(user_path.read_text(), source_path=user_path)
        bundled = Path(__file__).parent / "bundled" / "model_registry.yaml"
        if bundled.exists():
            return cls.from_yaml(bundled.read_text(), source_path=bundled)
        return cls()

    @classmethod
    def from_yaml(cls, yaml_str: str, source_path: Optional[Path] = None) -> "ModelRegistry":
        data = yaml.safe_load(yaml_str) or {}
        spec = data.get("spec", data)
        raw_models = spec.get("models", {})
        models: Dict[str, ModelCapability] = {}
        for model_id, model_data in raw_models.items():
            if isinstance(model_data, dict):
                models[model_id] = ModelCapability.from_dict(model_id, model_data)
        return cls(models=models, source_path=source_path)

    def to_yaml(self) -> str:
        data = {
            "apiVersion": "iris.io/v1alpha1",
            "kind": "ModelRegistry",
            "metadata": {"name": "default"},
            "spec": {
                "models": {
                    model_id: capability.to_dict()
                    for model_id, capability in sorted(self.models.items())
                }
            },
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
