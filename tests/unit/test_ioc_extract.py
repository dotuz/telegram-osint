import pytest

from intelligence.ioc.extract import extract_iocs, refang

pytestmark = pytest.mark.unit


def _by_type(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in extract_iocs(text):
        out.setdefault(m.ioc_type, []).append(m.normalized)
    return out


def test_refang_common_styles():
    assert refang("hxxps://a[.]b") == "https://a.b"
    assert refang("a (dot) b") == "a.b"
    assert refang("user [at] host [dot] com") == "user@host.com"


def test_url_also_yields_domain():
    res = _by_type("see https://Down.Example.com/x?a=1 now")
    assert res["url"] == ["https://down.example.com/x?a=1"]
    assert res["domain"] == ["down.example.com"]


def test_email_and_its_domain():
    res = _by_type("contact Bob@Mail.Example.org please")
    assert res["email"] == ["bob@mail.example.org"]
    assert "mail.example.org" in res["domain"]


def test_ipv4_valid_only():
    res = _by_type("host 8.8.8.8 not 999.1.1.1 and version 1.2.3.4.5")
    assert res["ipv4"] == ["8.8.8.8"]


def test_ipv6():
    res = _by_type("v6 2001:db8::dead:beef here")
    assert res.get("ipv6") == ["2001:db8::dead:beef"]


def test_hash_length_anchoring():
    md5 = "d41d8cd98f00b204e9800998ecf8427e"
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    res = _by_type(f"{md5} and {sha256}")
    assert res["md5"] == [md5]
    assert res["sha256"] == [sha256]
    assert "sha1" not in res


def test_cve_uppercased():
    assert _by_type("cve-2026-0001 patched")["cve"] == ["CVE-2026-0001"]


def test_telegram_username_and_url():
    res = _by_type("join t.me/opsecnews or ping @some_user")
    assert "opsecnews" in res["telegram_username"]
    assert "some_user" in res["telegram_username"]
    assert res["telegram_url"] == ["http://t.me/opsecnews"]


def test_short_at_handle_ignored():
    # Telegram usernames are >= 5 chars.
    assert "telegram_username" not in _by_type("hi @abc there")


def test_filename_not_treated_as_domain():
    assert "domain" not in _by_type("open report.pdf and script.py")


def test_dedupes_repeated_indicator():
    matches = extract_iocs("evil.com evil.com EVIL.com")
    domains = [m for m in matches if m.ioc_type == "domain"]
    assert len(domains) == 1


def test_empty_text():
    assert extract_iocs("") == []
    assert extract_iocs(None) == []  # type: ignore[arg-type]
