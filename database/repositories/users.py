"""User repository."""

from __future__ import annotations

from sqlalchemy import func, select

from database.models.user import User
from database.repositories.base import BaseRepository
from database.types import Role


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        *,
        email: str,
        display_name: str | None = None,
        role: Role = Role.ANALYST,
        telegram_user_id: int | None = None,
        password: str | None = None,
    ) -> User:
        from security.auth import hash_password

        user = User(
            email=email.strip().lower(),
            display_name=display_name,
            role=role.value,
            telegram_user_id=telegram_user_id,
            hashed_password=hash_password(password) if password else None,
        )
        return self.add(user)

    def set_password(self, user: User, password: str) -> None:
        from security.auth import hash_password

        user.hashed_password = hash_password(password)
        self.session.flush()

    def get_or_create_for_telegram(
        self, telegram_user_id: int, *, role: Role = Role.ANALYST
    ) -> tuple[User, bool]:
        existing = self.get_by_telegram_id(telegram_user_id)
        if existing is not None:
            return existing, False
        user = self.create(
            email=f"telegram-{telegram_user_id}@users.noreply.local",
            telegram_user_id=telegram_user_id,
            role=role,
        )
        return user, True

    def record_referral(self, user: User, *, inviter_telegram_id: int) -> bool:
        """Set ``user.invited_by_telegram_id`` once, at first contact only.

        Returns ``False`` (no-op) for self-referral or if already recorded --
        the referrer count this feeds is a one-time credit, not something a
        user can inflate by re-sending their own link to themselves.
        """
        if user.invited_by_telegram_id is not None:
            return False
        if inviter_telegram_id == user.telegram_user_id:
            return False
        user.invited_by_telegram_id = inviter_telegram_id
        self.session.flush()
        return True

    def count_referrals(self, telegram_user_id: int) -> int:
        stmt = select(func.count()).where(User.invited_by_telegram_id == telegram_user_id)
        return int(self.session.execute(stmt).scalar() or 0)

    def consume_free_action(self, user: User) -> None:
        user.free_actions_used += 1
        self.session.flush()
