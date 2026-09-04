"""Append-only audit log for security-sensitive actions.

Rows are never updated or deleted by application code. Never store passwords,
tokens, OTPs, cookies, or secrets here -- only references and outcomes.
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, new_uuid


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    # Actor: "telegram:<id>", "user:<uuid>", "system", "worker:<name>"
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    # Resource touched, e.g. "target:<id>", "report:<id>", "watchlist:<id>"
    resource: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # "success" | "denied" | "error"
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")

    # Coarse network metadata only (e.g. truncated IP / ASN); optional.
    ip_metadata: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Extra structured context as JSON text; must not contain secrets.
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_actor", "actor"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_resource", "resource"),
        Index("ix_audit_log_created_at", "created_at"),
    )
