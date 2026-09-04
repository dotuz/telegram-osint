"""Built-in username-OSINT adapters.

Each adapter only reads **public** endpoints. No login, no scraping behind auth.
The HTTP adapters take an injected :class:`SafeFetcher` so they are SSRF-guarded
and testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

from collectors.common.http import FetchError, SafeFetcher, SsrfBlocked
from collectors.common.interfaces import HealthStatus
from collectors.username.base import AdapterResult, ProfileFacts, UsernameAdapter
from database.normalize import normalize_username
from security.config import get_settings


def _clean(username: str) -> str:
    return normalize_username(username)


# --------------------------------------------------------------------------- GitHub


@dataclass
class GitHubAdapter(UsernameAdapter):
    platform = "github"
    url_template = "https://github.com/{username}"
    fetcher: SafeFetcher | None = None

    def _f(self) -> SafeFetcher:
        return self.fetcher or SafeFetcher()

    async def check(self, username: str) -> AdapterResult:
        handle = _clean(username)
        api = f"https://api.github.com/users/{handle}"
        headers = {"Accept": "application/vnd.github+json"}
        token = get_settings().github_token
        if token is not None and token.get_secret_value():
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        try:
            resp = await self._f().get(api, headers=headers, accept_statuses={200, 404})
        except (SsrfBlocked, FetchError) as exc:
            return AdapterResult.failed(self.platform, handle, str(exc))

        if resp.status_code == 404:
            return AdapterResult.not_found(self.platform, handle, self.profile_url(handle))
        if not resp.ok:
            return AdapterResult.failed(
                self.platform, handle, f"github api status {resp.status_code}"
            )

        try:
            data = resp.json()
            assert isinstance(data, dict)
        except (ValueError, AssertionError):
            return AdapterResult.failed(self.platform, handle, "unparseable github response")

        facts = ProfileFacts(
            display_name=data.get("name"),
            bio=data.get("bio"),
            website=data.get("blog") or None,
            email=data.get("email"),
            location=data.get("location"),
            avatar_reference=data.get("avatar_url"),
            account_id=str(data.get("id")) if data.get("id") is not None else None,
            created_at=data.get("created_at"),
            extra={"followers": data.get("followers"), "public_repos": data.get("public_repos")},
        )
        evidence = [f"GET {api} -> 200", f"login={data.get('login')}"]
        return AdapterResult(
            platform=self.platform,
            username=handle,
            exists=True,
            url=data.get("html_url") or self.profile_url(handle),
            facts=facts,
            match_confidence=90,
            evidence=tuple(evidence),
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(name=self.platform, healthy=True, detail="api.github.com")


# --------------------------------------------------------------------------- Reddit


@dataclass
class RedditAdapter(UsernameAdapter):
    platform = "reddit"
    url_template = "https://www.reddit.com/user/{username}"
    fetcher: SafeFetcher | None = None

    def _f(self) -> SafeFetcher:
        return self.fetcher or SafeFetcher()

    async def check(self, username: str) -> AdapterResult:
        handle = _clean(username)
        api = f"https://www.reddit.com/user/{handle}/about.json"
        try:
            resp = await self._f().get(
                api, headers={"Accept": "application/json"}, accept_statuses={200, 404, 403}
            )
        except (SsrfBlocked, FetchError) as exc:
            return AdapterResult.failed(self.platform, handle, str(exc))

        if resp.status_code in (404, 403):
            return AdapterResult.not_found(self.platform, handle, self.profile_url(handle))
        if not resp.ok:
            return AdapterResult.failed(self.platform, handle, f"reddit status {resp.status_code}")

        try:
            payload = resp.json()
            data = payload["data"] if isinstance(payload, dict) else {}
        except (ValueError, KeyError, TypeError):
            return AdapterResult.failed(self.platform, handle, "unparseable reddit response")

        sub = data.get("subreddit") or {}
        facts = ProfileFacts(
            display_name=data.get("subreddit", {}).get("title") or data.get("name"),
            bio=sub.get("public_description") or None,
            avatar_reference=(data.get("icon_img") or "").split("?")[0] or None,
            account_id=data.get("id"),
            created_at=str(data.get("created_utc")) if data.get("created_utc") else None,
            extra={
                "total_karma": data.get("total_karma"),
                "verified": data.get("verified"),
                "is_employee": data.get("is_employee"),
            },
        )
        return AdapterResult(
            platform=self.platform,
            username=handle,
            exists=True,
            url=self.profile_url(handle),
            facts=facts,
            match_confidence=85,
            evidence=(f"GET {api} -> 200", f"karma={data.get('total_karma')}"),
        )


# ----------------------------------------------------------------- generic web probe


@dataclass
class WebProbeAdapter(UsernameAdapter):
    """Conservative existence probe for a public profile URL.

    A ``200`` with no negative marker -> likely exists (low confidence, since many
    sites soft-404 with 200). A ``404`` -> not found. Anything else -> unknown.
    """

    platform: str = "web"
    url_template: str | None = None
    negative_markers: tuple[str, ...] = ()
    fetcher: SafeFetcher | None = None
    confidence_if_found: int = 45

    def _f(self) -> SafeFetcher:
        return self.fetcher or SafeFetcher()

    async def check(self, username: str) -> AdapterResult:
        handle = _clean(username)
        url = self.profile_url(handle)
        if url is None:
            return AdapterResult.failed(self.platform, handle, "no url_template configured")
        try:
            resp = await self._f().get(url, accept_statuses={200, 301, 302, 404, 403, 410})
        except (SsrfBlocked, FetchError) as exc:
            return AdapterResult.failed(self.platform, handle, str(exc))

        if resp.status_code in (404, 410):
            return AdapterResult.not_found(self.platform, handle, url)
        if resp.status_code != 200:
            return AdapterResult(
                platform=self.platform,
                username=handle,
                exists=False,
                url=url,
                error=f"inconclusive status {resp.status_code}",
            )
        low = resp.text.lower()
        if any(marker.lower() in low for marker in self.negative_markers):
            return AdapterResult.not_found(self.platform, handle, url)
        return AdapterResult(
            platform=self.platform,
            username=handle,
            exists=True,
            url=url,
            facts=ProfileFacts(),
            match_confidence=self.confidence_if_found,
            evidence=(f"GET {url} -> 200",),
        )


def default_web_adapters(fetcher: SafeFetcher | None = None) -> list[WebProbeAdapter]:
    """A modest set of public profile probes. Extend freely."""
    specs = [
        ("x", "https://nitter.net/{username}", ("user not found", "tweets, no tweets")),
        (
            "instagram",
            "https://www.instagram.com/{username}/",
            ("page not found", "sorry, this page"),
        ),
        ("youtube", "https://www.youtube.com/@{username}", ("this page isn't available",)),
        ("tiktok", "https://www.tiktok.com/@{username}", ("couldn't find this account",)),
        ("keybase", "https://keybase.io/{username}", ("not found",)),
        ("gitlab", "https://gitlab.com/{username}", ("page not found",)),
    ]
    return [
        WebProbeAdapter(
            platform=p,
            url_template=t,
            negative_markers=m,
            fetcher=fetcher,
        )
        for p, t, m in specs
    ]


# ------------------------------------------------------------------ Telegram presence


@dataclass
class TelegramPresenceAdapter(UsernameAdapter):
    platform = "telegram"
    url_template = "https://t.me/{username}"
    source: object | None = None  # collectors.telegram.source.TelegramSource

    def _source(self):  # noqa: ANN202
        if self.source is not None:
            return self.source
        from collectors.telegram.source import build_source

        return build_source()

    async def check(self, username: str) -> AdapterResult:
        handle = _clean(username)
        src = self._source()
        try:
            if not await src.available():
                return AdapterResult.failed(self.platform, handle, "no telegram source configured")
            profile = await src.get_profile(handle)
            chat = None if profile else await src.get_chat(handle)
        except Exception as exc:  # noqa: BLE001
            return AdapterResult.failed(self.platform, handle, str(exc))

        obj = profile or chat
        if obj is None:
            return AdapterResult.not_found(self.platform, handle, self.profile_url(handle))

        facts = ProfileFacts(
            display_name=getattr(obj, "display_name", None) or getattr(obj, "title", None),
            bio=getattr(obj, "bio", None) or getattr(obj, "description", None),
            avatar_reference=getattr(obj, "photo_reference", None),
            account_id=str(getattr(obj, "telegram_id", "") or "") or None,
        )
        return AdapterResult(
            platform=self.platform,
            username=handle,
            exists=True,
            url=getattr(obj, "reference", None) or self.profile_url(handle),
            facts=facts,
            match_confidence=80,
            evidence=("telegram public lookup -> found",),
        )


__all__ = [
    "GitHubAdapter",
    "RedditAdapter",
    "TelegramPresenceAdapter",
    "WebProbeAdapter",
    "default_web_adapters",
]
