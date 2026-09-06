"""Built-in job handlers.

Each handler runs one of the Phase 4–6 intelligence services and formats a
Telegram-ready notification with the existing view functions. Collectors are
overridable (``set_collector_overrides``) so worker tests run fully offline.
"""

from __future__ import annotations

from apps.bot.intel_views import (
    render_chat_intel,
    render_user_intel,
    render_username_osint,
    render_watch_activity,
)
from collectors.common.interfaces import Collector
from collectors.telegram.collector import KIND_CHANNEL, KIND_GROUP, TelegramPublicCollector
from database.models.user import User
from database.models.watchlist import Watchlist
from intelligence.monitoring import WatchMonitor
from intelligence.search import TelegramIntelService
from intelligence.username_osint import UsernameOsintService
from workers.registry import JobContext, JobOutcome, Notification, register

_TG_COLLECTOR: Collector | None = None
_USERNAME_COLLECTOR: Collector | None = None


def set_collector_overrides(
    *, telegram: Collector | None = None, username: Collector | None = None
) -> None:
    global _TG_COLLECTOR, _USERNAME_COLLECTOR
    _TG_COLLECTOR = telegram
    _USERNAME_COLLECTOR = username


def _tg_collector() -> Collector:
    return _TG_COLLECTOR or TelegramPublicCollector()


def _notify(ctx: JobContext, text: str) -> Notification | None:
    chat_id = ctx.params.get("chat_id")
    return Notification(chat_id=chat_id, text=text) if chat_id is not None else None


@register("telegram_user")
async def run_telegram_user(ctx: JobContext) -> JobOutcome:
    p = ctx.params
    ctx.progress(10)
    svc = TelegramIntelService(ctx.session, p["user_id"], collector=_tg_collector())
    r = await svc.search_user(p["query"])
    ctx.progress(90)
    text = render_user_intel(
        query=p["query"], found=r.found, summary=r.summary, notes=r.notes, entity_id=r.entity_id
    ).text
    return JobOutcome(
        summary={"found": r.found, "entity_id": r.entity_id, "search_id": r.search_id},
        notification=_notify(ctx, text),
    )


@register("telegram_group")
async def run_telegram_group(ctx: JobContext) -> JobOutcome:
    return await _run_chat(ctx, KIND_GROUP)


@register("telegram_channel")
async def run_telegram_channel(ctx: JobContext) -> JobOutcome:
    return await _run_chat(ctx, KIND_CHANNEL)


async def _run_chat(ctx: JobContext, kind: str) -> JobOutcome:
    p = ctx.params
    ctx.progress(10)
    svc = TelegramIntelService(ctx.session, p["user_id"], collector=_tg_collector())
    method = svc.group_intel if kind == KIND_GROUP else svc.channel_intel
    r = await method(p["query"])
    ctx.progress(90)
    text = render_chat_intel(
        kind=r.kind, query=p["query"], found=r.found, summary=r.summary, notes=r.notes
    ).text
    return JobOutcome(
        summary={"found": r.found, "entity_id": r.entity_id},
        notification=_notify(ctx, text),
    )


@register("username_osint")
async def run_username_osint(ctx: JobContext) -> JobOutcome:
    p = ctx.params
    ctx.progress(10)
    svc = UsernameOsintService(ctx.session, p["user_id"], collector=_USERNAME_COLLECTOR)
    r = await svc.run(p["query"])
    ctx.progress(90)
    text = render_username_osint(
        username=r.username,
        found=r.found,
        sources=[
            {
                "platform": s.platform,
                "url": s.url,
                "confidence": s.confidence,
                "evidence": s.evidence,
            }
            for s in r.sources
        ],
        notes=r.notes,
        disclaimer=r.disclaimer,
    ).text
    return JobOutcome(
        summary={"found": r.found, "sources": len(r.sources), "target_id": r.target_id},
        notification=_notify(ctx, text),
    )


@register("investigation")
async def run_investigation(ctx: JobContext) -> JobOutcome:
    from apps.bot.intel_views import render_investigation_result
    from intelligence.investigation import InvestigationService, link_job

    p = ctx.params
    inv_id = p["investigation_id"]
    link_job(ctx.session, inv_id, ctx.job.id)
    ctx.progress(10)

    svc = InvestigationService(
        ctx.session,
        p["user_id"],
        telegram_collector=_TG_COLLECTOR,
        username_collector=_USERNAME_COLLECTOR,
    )
    result = await svc.run(inv_id)
    ctx.progress(95)

    notification = None
    chat_id = p.get("chat_id")
    if chat_id is not None:
        notification = Notification(chat_id=chat_id, text=render_investigation_result(result).text)
    return JobOutcome(
        summary={
            "investigation": result.public_id,
            "status": result.status,
            "counts": result.counts,
            "confidence": result.confidence,
            "report_id": result.report_id,
        },
        notification=notification,
    )


@register("report_generate")
async def run_report_generate(ctx: JobContext) -> JobOutcome:
    from reports.service import generate_report

    p = ctx.params
    ctx.progress(15)
    result = generate_report(ctx.session, p["report_id"], formats=p.get("formats"))
    ctx.progress(95)

    chat_id = p.get("chat_id")
    notification = None
    if chat_id is not None:
        fmts = ", ".join(sorted(result.artifacts)) or "none"
        if result.status == "COMPLETED":
            text = (
                f"*Report ready* ({result.section_count} sections, formats: {fmts}).\n\n"
                f"{result.summary or ''}\n\n"
                f"_Download: /report list or the API "
                f"(`/api/v1/reports/{result.report_id[:8]}…/download?fmt=json`)._"
            )
        else:
            text = "Report generation failed. " + "; ".join(result.notes)
        notification = Notification(chat_id=chat_id, text=text)

    return JobOutcome(
        summary={
            "status": result.status,
            "artifacts": list(result.artifacts),
            "sections": result.section_count,
        },
        notification=notification,
    )


@register("watch_poll")
async def run_watch_poll(ctx: JobContext) -> JobOutcome:
    wid = ctx.params["watchlist_id"]
    entry = ctx.session.get(Watchlist, wid)
    if entry is None or not entry.is_active:
        return JobOutcome(summary={"skipped": True})

    monitor = WatchMonitor(
        ctx.session,
        telegram_collector=_TG_COLLECTOR,
        username_collector=_USERNAME_COLLECTOR,
    )
    result = await monitor.poll(entry)
    ctx.progress(90)

    notification = None
    if result.activities:
        user = ctx.session.get(User, entry.user_id)
        chat_id = user.telegram_user_id if user is not None else None
        if chat_id is not None:
            notification = Notification(
                chat_id=chat_id,
                text=render_watch_activity(
                    target=result.target,
                    activities=[a.as_dict() for a in result.activities],
                ).text,
            )
    return JobOutcome(
        summary={"activities": len(result.activities), "notes": result.notes},
        notification=notification,
    )


__all__ = ["set_collector_overrides"]
