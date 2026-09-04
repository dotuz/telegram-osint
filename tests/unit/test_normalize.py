import pytest

from database.normalize import (
    normalize_domain,
    normalize_email,
    normalize_ip,
    normalize_url,
    normalize_username,
    url_hash,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Alice", "alice"),
        ("  ALICE  ", "alice"),
        ("https://t.me/Alice", "alice"),
        ("t.me/alice/123", "alice"),
        ("alice?start=x", "alice"),
    ],
)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("www.example.com.", "example.com"),
        ("https://sub.Example.com/path", "sub.example.com"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_email():
    assert normalize_email("  Bob@Example.COM ") == "bob@example.com"


def test_normalize_url_collapses_equivalent_forms():
    a = normalize_url("http://Example.com:80/a/b?q=1#frag")
    b = normalize_url("example.com/a/b?q=1")
    assert a == b == "http://example.com/a/b?q=1"
    assert url_hash(a) == url_hash(b)


def test_normalize_ip():
    assert normalize_ip(" 127.0.0.1 ") == "127.0.0.1"
    assert normalize_ip("2001:0db8::1") == "2001:db8::1"
