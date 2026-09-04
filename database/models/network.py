"""Network entities: domains, URLs, IP addresses (shared, deduplicated)."""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class Domain(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "domain"

    name: Mapped[str] = mapped_column(String(253), nullable=False)  # as observed
    name_normalized: Mapped[str] = mapped_column(String(253), nullable=False)
    tld: Mapped[str | None] = mapped_column(String(63), nullable=True)
    is_public_suffix: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("name_normalized", name="uq_domain_name_normalized"),
        Index("ix_domain_name_normalized", "name_normalized"),
    )


class URL(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "url"

    # Full URLs can be long; dedup on a sha256 of the normalized form.
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scheme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    host: Mapped[str | None] = mapped_column(String(253), nullable=True)

    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_url_hash"),
        Index("ix_url_hash", "url_hash"),
        Index("ix_url_host", "host"),
    )


class IP(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ip"

    address: Mapped[str] = mapped_column(String(45), nullable=False)  # normalized
    version: Mapped[int] = mapped_column(nullable=False, default=4)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    asn: Mapped[int | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    __table_args__ = (
        UniqueConstraint("address", name="uq_ip_address"),
        Index("ix_ip_address", "address"),
    )
