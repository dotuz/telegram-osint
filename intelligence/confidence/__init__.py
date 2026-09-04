"""Confidence scoring (0-100) from weighted public evidence.

Never asserts identity -- the strongest output is a "high-confidence potential
match". See :mod:`intelligence.confidence.engine`.
"""

from intelligence.confidence.engine import (
    ConfidenceResult,
    IdentityFacts,
    Signal,
    assert_safe_phrasing,
    score_account,
    score_pair,
)

__all__ = [
    "ConfidenceResult",
    "IdentityFacts",
    "Signal",
    "assert_safe_phrasing",
    "score_account",
    "score_pair",
]
