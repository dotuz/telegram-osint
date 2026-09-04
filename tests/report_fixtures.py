"""Phase-10 helper: populate a target with collected intel and return its id."""

from __future__ import annotations

from collectors.telegram.collector import TelegramPublicCollector
from database.repositories import ReportRepository
from intelligence import TelegramIntelService, UsernameOsintService
from tests.telegram_fixtures import seeded_source
from tests.username_fixtures import alice_collector


async def seed_target(session, user_id: str) -> str:
    """Collect data and return a resolved ``username`` target id (what /report uses)."""
    from database.repositories import TargetRepository
    from database.types import TargetKind
    from intelligence.entity_resolution import TargetResolver

    svc = TelegramIntelService(session, user_id, collector=TelegramPublicCollector(seeded_source()))
    await svc.search_user("@alice")
    await svc.channel_intel("opsecnews")
    await UsernameOsintService(session, user_id, collector=alice_collector()).run("alice")
    session.flush()

    target, _ = TargetRepository(session, user_id).get_or_create(
        kind=TargetKind.USERNAME, value="alice"
    )
    session.flush()
    TargetResolver(session).resolve(target)
    session.flush()
    return target.id


def make_report(session, user_id: str, target_id: str, title: str = "test report") -> str:
    report = ReportRepository(session, user_id).create(title=title, target_id=target_id)
    session.flush()
    return report.id
