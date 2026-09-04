"""Repository layer: the only place that builds queries against ORM models.

Application/handler code depends on repositories, never on raw SQLAlchemy
sessions scattered through business logic. All queries are parameterised by
SQLAlchemy; raw SQL string concatenation is forbidden.
"""

from database.repositories.audit import AuditRepository

__all__ = ["AuditRepository"]
