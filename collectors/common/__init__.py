"""Shared collector contracts.

Every collector implements :class:`Collector` (``collect`` -> ``normalize`` ->
``validate`` -> ``health_check``) and returns plain DTOs plus evidence drafts.
Collectors never touch the database or the intelligence engine -- the ingestion
layer (``intelligence.ingest``) persists their output.
"""

from collectors.common.interfaces import (
    Collector,
    CollectorError,
    CollectRequest,
    CollectResult,
    EvidenceDraft,
    HealthStatus,
    NormalizedRecord,
    RawBundle,
    RelationshipDraft,
)
from collectors.common.registry import CollectorRegistry, registry

__all__ = [
    "CollectRequest",
    "CollectResult",
    "Collector",
    "CollectorError",
    "CollectorRegistry",
    "EvidenceDraft",
    "HealthStatus",
    "NormalizedRecord",
    "RawBundle",
    "RelationshipDraft",
    "registry",
]
