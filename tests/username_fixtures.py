"""Shared Phase-6 helpers: fake username adapters + collector, mock HTTP transport."""

from __future__ import annotations

import json

import httpx

from collectors.common.http import SafeFetcher
from collectors.username.base import AdapterResult, ProfileFacts, UsernameAdapter
from collectors.username.collector import UsernameOsintCollector


class FakeAdapter(UsernameAdapter):
    def __init__(self, platform: str, result: AdapterResult | Exception) -> None:
        self.platform = platform
        self.url_template = f"https://{platform}.test/{{username}}"
        self._result = result

    async def check(self, username: str) -> AdapterResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def found(platform: str, handle: str, *, match_confidence: int = 85, **facts) -> AdapterResult:
    return AdapterResult(
        platform=platform,
        username=handle,
        exists=True,
        url=f"https://{platform}.test/{handle}",
        facts=ProfileFacts(**facts),
        match_confidence=match_confidence,
        evidence=(f"GET https://{platform}.test/{handle} -> 200",),
    )


def alice_collector() -> UsernameOsintCollector:
    return UsernameOsintCollector(
        [
            FakeAdapter(
                "github",
                found(
                    "github",
                    "alice",
                    display_name="Alice Anderson",
                    website="https://alice.example",
                    bio="security researcher and coffee",
                ),
            ),
            FakeAdapter(
                "telegram",
                found(
                    "telegram", "alice", display_name="Alice Anderson", bio="security researcher"
                ),
            ),
            FakeAdapter(
                "reddit", AdapterResult.not_found("reddit", "alice", "https://reddit.test/alice")
            ),
            FakeAdapter("gitlab", RuntimeError("boom")),
        ]
    )


def mock_fetcher(routes: dict[str, tuple[int, str] | tuple[int, str, dict]]) -> SafeFetcher:
    """routes: url-substring -> (status, body[, headers])."""

    def handler(request: httpx.Request) -> httpx.Response:
        for frag, spec in routes.items():
            if frag in str(request.url):
                status, body = spec[0], spec[1]
                headers = spec[2] if len(spec) > 2 else {}
                return httpx.Response(status, text=body, headers=headers)
        return httpx.Response(404, text="not found")

    fetcher = SafeFetcher(transport=httpx.MockTransport(handler))
    # tests hit *.test / example hosts; allow private so DNS isn't required
    fetcher.settings.http_fetch_allow_private = True
    return fetcher


def gh_json(login: str = "alice", **over) -> str:
    base = {
        "login": login,
        "id": 42,
        "name": "Alice Anderson",
        "blog": "https://alice.example",
        "bio": "security researcher",
        "location": "Tashkent",
        "email": None,
        "avatar_url": "https://avatars.example/alice.png",
        "html_url": f"https://github.com/{login}",
        "created_at": "2015-01-01T00:00:00Z",
        "followers": 10,
        "public_repos": 5,
    }
    base.update(over)
    return json.dumps(base)
