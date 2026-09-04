import pytest

from apps.bot.auth import (
    AccessDenied,
    Role,
    require_admin,
    resolve_principal,
    warn_if_open_or_closed,
)
from security.config import Settings

pytestmark = pytest.mark.unit


def _settings(**kw):
    base = dict(
        telegram_allowed_user_ids="111,222",
        telegram_admin_user_ids="111",
        _env_file=None,
    )
    base.update(kw)
    return Settings(**base)


def test_admin_id_resolves_to_admin_role():
    p = resolve_principal(111, _settings())
    assert p.role is Role.ADMIN
    assert p.is_admin
    assert p.actor == "telegram:111"


def test_allowlisted_non_admin_is_analyst():
    p = resolve_principal(222, _settings())
    assert p.role is Role.ANALYST
    assert not p.is_admin


def test_unknown_user_denied():
    with pytest.raises(AccessDenied) as ei:
        resolve_principal(999, _settings())
    assert ei.value.telegram_id == 999
    assert "allow-list" in ei.value.reason


def test_missing_id_denied():
    with pytest.raises(AccessDenied):
        resolve_principal(None, _settings())


def test_require_admin_rejects_analyst():
    p = resolve_principal(222, _settings())
    with pytest.raises(AccessDenied, match="admin role required"):
        require_admin(p)


def test_empty_allowlist_denies_everyone():
    s = _settings(telegram_allowed_user_ids="", telegram_admin_user_ids="")
    with pytest.raises(AccessDenied):
        resolve_principal(111, s)


def test_warn_if_open_or_closed_logs_on_empty(caplog):
    s = _settings(telegram_allowed_user_ids="", telegram_admin_user_ids="")
    warn_if_open_or_closed(s)  # must not raise
