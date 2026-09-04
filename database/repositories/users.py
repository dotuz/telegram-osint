"""User repository."""

from __future__ import annotations

from sqlalchemy import select

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
    ) -> User:
        user = User(
            email=email.strip().lower(),
            display_name=display_name,
            role=role.value,
            telegram_user_id=telegram_user_id,
        )
        return self.add(user)

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
