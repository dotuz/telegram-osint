import pytest

from intelligence.confidence import IdentityFacts, assert_safe_phrasing, score_account, score_pair

pytestmark = pytest.mark.unit


def test_username_only_baseline():
    r = score_pair(IdentityFacts(), IdentityFacts(), same_username=True)
    assert r.score == 25
    assert r.band == "low"
    assert any(s.name == "exact_username" for s in r.signals)


def test_strong_corroboration_is_high_band():
    a = IdentityFacts(
        display_name="Alice Anderson", website="https://alice.dev", email="alice@alice.dev"
    )
    b = IdentityFacts(
        display_name="Alice Anderson", website="http://www.alice.dev/blog", email="alice@alice.dev"
    )
    r = score_pair(a, b)
    assert r.score >= 75
    assert r.band == "high"
    names = {s.name for s in r.signals}
    assert {"exact_username", "display_name_exact", "website_same_domain", "email_exact"} <= names


def test_label_never_claims_identity():
    a = IdentityFacts(
        display_name="X Y", website="https://x.y", email="x@x.y", bio="hello world foo"
    )
    b = IdentityFacts(
        display_name="X Y", website="https://x.y", email="x@x.y", bio="hello world foo"
    )
    r = score_pair(a, b)
    assert_safe_phrasing(r.label)
    for line in r.evidence_lines:
        assert_safe_phrasing(line)
    assert "potential match" in r.label.lower()


def test_assert_safe_phrasing_catches_bad_output():
    with pytest.raises(AssertionError):
        assert_safe_phrasing("These are definitely the same person.")


def test_score_account_takes_strongest_peer():
    target = IdentityFacts(display_name="Alice Anderson")
    peers = [
        IdentityFacts(display_name="Someone Else"),
        IdentityFacts(display_name="Alice Anderson"),
    ]
    r = score_account(target, peers)
    assert r.score == 50  # exact_username(25) + display_name_exact(25)


def test_score_is_capped_at_100():
    a = IdentityFacts(
        display_name="A B",
        website="https://a.b",
        email="a@a.b",
        bio="one two three four five",
        location="Berlin",
        avatar_reference="x",
    )
    r = score_pair(a, a)
    assert r.score == 100
