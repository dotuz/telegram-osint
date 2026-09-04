import httpx
import pytest

from collectors.username.adapters import GitHubAdapter, RedditAdapter, WebProbeAdapter
from tests.username_fixtures import gh_json, mock_fetcher

pytestmark = pytest.mark.unit


async def test_github_found():
    a = GitHubAdapter(fetcher=mock_fetcher({"api.github.com/users/alice": (200, gh_json())}))
    r = await a.check("@Alice")
    assert r.exists
    assert r.facts.display_name == "Alice Anderson"
    assert r.facts.website == "https://alice.example"
    assert r.facts.account_id == "42"
    assert r.match_confidence == 90


async def test_github_not_found():
    a = GitHubAdapter(fetcher=mock_fetcher({"api.github.com": (404, '{"message":"Not Found"}')}))
    r = await a.check("ghost")
    assert r.exists is False
    assert r.error is None
    assert r.url == "https://github.com/ghost"


async def test_github_ssrf_block_becomes_failed_result():
    # allow_private=False by default -> the mock host won't resolve; force a block
    a = GitHubAdapter(fetcher=mock_fetcher({}))
    a.fetcher.settings.http_fetch_allow_private = False
    a.fetcher.resolver = lambda h: ["10.0.0.1"]
    r = await a.check("alice")
    assert r.exists is False
    assert r.error and "non-public" in r.error


async def test_reddit_found_and_notfound():
    body = '{"data":{"name":"alice","total_karma":1234,"subreddit":{"public_description":"hi"}}}'
    ra = RedditAdapter(fetcher=mock_fetcher({"/user/alice/about.json": (200, body)}))
    r = await ra.check("alice")
    assert r.exists and r.facts.bio == "hi"

    rn = RedditAdapter(fetcher=mock_fetcher({"about.json": (404, "{}")}))
    assert (await rn.check("ghost")).exists is False


async def test_web_probe_marker_detection():
    wp = WebProbeAdapter(
        platform="x",
        url_template="https://x.test/{username}",
        negative_markers=("user not found",),
        fetcher=mock_fetcher({"x.test/ghost": (200, "sorry, user not found here")}),
    )
    assert (await wp.check("ghost")).exists is False

    wp2 = WebProbeAdapter(
        platform="x",
        url_template="https://x.test/{username}",
        negative_markers=("user not found",),
        fetcher=mock_fetcher({"x.test/alice": (200, "<title>alice</title>")}),
    )
    r = await wp2.check("alice")
    assert r.exists and r.match_confidence == 45


async def test_web_probe_network_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    f = mock_fetcher({})
    f.transport = httpx.MockTransport(boom)
    wp = WebProbeAdapter(platform="x", url_template="https://x.test/{username}", fetcher=f)
    r = await wp.check("alice")
    assert r.exists is False and r.error
