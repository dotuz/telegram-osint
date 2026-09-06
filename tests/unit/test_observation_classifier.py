import pytest

from database.types import ObservationType
from intelligence.investigation import classify_observation, parse_target

pytestmark = pytest.mark.unit

TGT = parse_target("@example")
ID_TGT = parse_target("55555")


def test_author_requires_matching_author_field():
    t, conf = classify_observation(target=TGT, author_username="Example", text="hello world")
    assert t is ObservationType.AUTHOR
    assert conf >= 90


def test_mention_is_never_promoted_to_author():
    # target's handle only appears in the body, author is someone else
    t, _ = classify_observation(
        target=TGT, author_username="someone_else", text="hey @example check this"
    )
    assert t is ObservationType.MENTION


def test_reply_classification():
    t, _ = classify_observation(
        target=TGT,
        author_username="third_party",
        text="@example you're wrong",
        is_reply=True,
    )
    assert t is ObservationType.REPLY


def test_plain_text_reference():
    t, _ = classify_observation(
        target=TGT, author_username="reporter", text="the account example was seen again"
    )
    assert t is ObservationType.REFERENCE


def test_unknown_when_no_association():
    t, _ = classify_observation(target=TGT, author_username="nobody", text="unrelated content")
    assert t is ObservationType.UNKNOWN


def test_numeric_id_author_match():
    t, _ = classify_observation(target=ID_TGT, author_id=55555, text="anything")
    assert t is ObservationType.AUTHOR


def test_numeric_id_non_match_is_unknown():
    t, _ = classify_observation(target=ID_TGT, author_id=999, text="anything")
    assert t is ObservationType.UNKNOWN


def test_mention_does_not_beat_author_when_both_present():
    # author matches AND body mentions the target -> AUTHOR wins, not MENTION
    t, _ = classify_observation(target=TGT, author_username="example", text="signed, @example")
    assert t is ObservationType.AUTHOR
