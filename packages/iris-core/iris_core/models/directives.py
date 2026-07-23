"""
Directive Registry — hot-reloadable emergency model suspensions and kill switches.

Used for government export-control directives, security incidents, and org-wide
model recalls. Loaded from governance/directives/active.yaml (local GitOps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from iris_core.models.governance_paths import find_governance_root


@dataclass
class ModelDirective:
    directive_id: str
    model_id: str
    status: str = "suspended"
    effective_at: Optional[str] = None
    reason: str = ""
    source: str = "internal"
    fallback_model: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelDirective":
        return cls(
            directive_id=str(data.get("directive_id", "")),
            model_id=str(data.get("model_id", "")),
            status=str(data.get("status", "suspended")),
            effective_at=data.get("effective_at"),
            reason=str(data.get("reason", "")),
            source=str(data.get("source", "internal")),
            fallback_model=data.get("fallback_model"),
        )

    def is_active(self) -> bool:
        return self.status.lower() in ("suspended", "blocked", "recalled")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directive_id": self.directive_id,
            "model_id": self.model_id,
            "status": self.status,
            "effective_at": self.effective_at,
            "reason": self.reason,
            "source": self.source,
            "fallback_model": self.fallback_model,
        }


@dataclass
class DirectiveRegistry:
    directives: List[ModelDirective] = field(default_factory=list)
    source_path: Optional[Path] = None
    loaded_at: Optional[datetime] = None

    def active_for_model(self, model_id: str) -> Optional[ModelDirective]:
        for directive in self.directives:
            if directive.model_id == model_id and directive.is_active():
                return directive
        return None

    def active_directives(self) -> List[ModelDirective]:
        return [d for d in self.directives if d.is_active()]

    @classmethod
    def load(cls, governance_root: Optional[Path] = None) -> "DirectiveRegistry":
        root = governance_root or find_governance_root()
        path = root / "directives" / "active.yaml"
        if not path.exists():
            return cls(source_path=path)
        return cls.from_yaml(path.read_text(), source_path=path)

    @classmethod
    def from_yaml(cls, yaml_str: str, source_path: Optional[Path] = None) -> "DirectiveRegistry":
        data = yaml.safe_load(yaml_str) or {}
        spec = data.get("spec", data)
        raw = spec.get("directives", [])
        directives = [
            ModelDirective.from_dict(item)
            for item in raw
            if isinstance(item, dict)
        ]
        return cls(
            directives=directives,
            source_path=source_path,
            loaded_at=datetime.utcnow(),
        )

    def to_yaml(self) -> str:
        data = {
            "apiVersion": "iris.io/v1alpha1",
            "kind": "DirectiveRegistry",
            "metadata": {"name": "active"},
            "spec": {
                "directives": [d.to_dict() for d in self.directives],
            },
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
