"""
Region policy models — cross-region data transfer detection.

Phase 1: configuration-driven. The customer defines which region
pairs are restricted. IRIS provides the tracking infrastructure.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TransferRule:
    from_region: str
    to_region: str
    compliance_ref: str
    action: str = "block"        # block | alert | log
    note: Optional[str] = None


@dataclass
class RegionPolicy:
    name: str
    restricted_transfers: List[TransferRule] = field(default_factory=list)
    allowed_transfers: List[TransferRule] = field(default_factory=list)


@dataclass
class EndpointRegionMap:
    host: str
    region: str
    data_classification: str = "general"
    track: bool = True
