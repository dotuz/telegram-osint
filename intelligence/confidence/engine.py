"""Correlation confidence engine (0-100).

Given the public :class:`IdentityFacts` for two accounts that share a username,
produce a score, a band, a **non-committal** human label, and the list of
signals that produced it. Evidence is always retained.

Hard rule: this engine never asserts identity. The strongest phrasing it emits
is *"high-confidence potential match based on available public evidence"* -- never
"the same person", "confirmed", or "definitely".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from database.normalize import normalize_domain, normalize_email


@dataclass(frozen=True)
class IdentityFacts:
    """Neutral, source-agnostic public signals for one account."""

    display_name: str | None = None
    bio: str | None = None
    website: str | None = None
    email: str | None = None
    location: str | None = None
    avatar_reference: str | None = None


_WORD_RE = re.compile(r"[^a-z0-9]+")

# signal name -> weight
_WEIGHTS = {
    "exact_username": 25,
    "display_name_exact": 25,
    "display_name_overlap": 12,
    "website_same_domain": 22,
    "bio_similar": 15,
    "email_exact": 30,
    "email_domain_match": 10,
    "avatar_exact": 15,
    "location_exact": 5,
}

_BANDS = (
    (75, "high", "High-confidence potential match based on available public evidence."),
    (45, "medium", "Possible match — several public signals align, but not conclusive."),
    (20, "low", "Weak signal — limited corroborating public evidence."),
    (
        0,
        "username_only",
        "Username match only — no corroborating evidence. Do not assume the same person.",
    ),
)

_FORBIDDEN_PHRASES = ("the same person", "definitely", "confirmed identity", "certainly")


@dataclass(frozen=True)
class Signal:
    name: str
    weight: int
    detail: str


@dataclass(frozen=True)
class ConfidenceResult:
    score: int
    band: str
    label: str
    signals: list[Signal] = field(default_factory=list)

    @property
    def evidence_lines(self) -> list[str]:
        return [f"{s.detail} (+{s.weight})" for s in self.signals]


def _norm_name(value: str | None) -> str:
    if not value:
        return ""
    return _WORD_RE.sub(" ", value.strip().lower()).strip()


def _tokens(value: str | None) -> set[str]:
    return {t for t in _norm_name(value).split() if len(t) > 2}


def _website_domain(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if "://" not in v:
        v = f"http://{v}"
    host = urlsplit(v).hostname
    return normalize_domain(host) if host else None


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_pair(
    a: IdentityFacts | None,
    b: IdentityFacts | None,
    *,
    same_username: bool = True,
) -> ConfidenceResult:
    signals: list[Signal] = []

    def add(name: str, detail: str) -> None:
        signals.append(Signal(name, _WEIGHTS[name], detail))

    if same_username:
        add("exact_username", "Exact username match")

    a = a or IdentityFacts()
    b = b or IdentityFacts()

    na, nb = _norm_name(a.display_name), _norm_name(b.display_name)
    if na and nb:
        if na == nb:
            add("display_name_exact", f"Matching display name ({a.display_name!r})")
        elif _jaccard(_tokens(a.display_name), _tokens(b.display_name)) >= 0.5:
            add("display_name_overlap", "Overlapping display-name tokens")

    da, db = _website_domain(a.website), _website_domain(b.website)
    if da and db and da == db:
        add("website_same_domain", f"Both link to {da}")

    if a.bio and b.bio and _jaccard(_tokens(a.bio), _tokens(b.bio)) >= 0.4:
        add("bio_similar", "Similar public bio text")

    ea = normalize_email(a.email) if a.email else None
    eb = normalize_email(b.email) if b.email else None
    if ea and eb and ea == eb:
        add("email_exact", f"Matching public email ({ea})")
    elif ea and eb and ea.split("@")[-1] == eb.split("@")[-1]:
        add("email_domain_match", "Matching public email domain")

    # website domain vs email domain cross-match
    for dom, email in ((da, eb), (db, ea)):
        if dom and email and dom == normalize_domain(email.split("@")[-1]):
            add("email_domain_match", "Website domain matches the other account's email domain")
            break

    if a.avatar_reference and b.avatar_reference and a.avatar_reference == b.avatar_reference:
        add("avatar_exact", "Identical public avatar reference")

    if a.location and b.location and _norm_name(a.location) == _norm_name(b.location):
        add("location_exact", f"Matching location ({a.location})")

    # de-dup signal names, keep highest weight
    best: dict[str, Signal] = {}
    for s in signals:
        if s.name not in best or s.weight > best[s.name].weight:
            best[s.name] = s
    ordered = sorted(best.values(), key=lambda s: -s.weight)

    raw = sum(s.weight for s in ordered)
    score = max(0, min(100, raw))
    band, label = _band(score)
    return ConfidenceResult(score=score, band=band, label=label, signals=ordered)


def score_account(
    facts: IdentityFacts | None,
    peers: list[IdentityFacts],
    *,
    same_username: bool = True,
) -> ConfidenceResult:
    """Aggregate confidence that ``facts`` is the same identity as the peer set.

    Takes the strongest pairwise result (union of its signals). With no peers it
    degrades to the username-only baseline.
    """
    if not peers:
        return score_pair(facts, None, same_username=same_username)
    results = [score_pair(facts, p, same_username=same_username) for p in peers]
    return max(results, key=lambda r: r.score)


def _band(score: int) -> tuple[str, str]:
    for threshold, name, label in _BANDS:
        if score >= threshold:
            return name, label
    return "username_only", _BANDS[-1][2]


def assert_safe_phrasing(text: str) -> None:
    """Guard used by report/AI code paths and tests."""
    low = text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in low:
            raise AssertionError(f"forbidden identity claim in output: {phrase!r}")
