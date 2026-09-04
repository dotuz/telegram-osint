"""Entity resolution / deduplication and target linking."""

from intelligence.entity_resolution.resolver import (
    MergeResult,
    ResolutionResult,
    TargetResolver,
    merge_entities,
)

__all__ = ["MergeResult", "ResolutionResult", "TargetResolver", "merge_entities"]
