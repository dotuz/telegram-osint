"""JSON renderer -- the canonical, machine-readable form."""

from __future__ import annotations

import json

from reports.models import ReportContent


def render_json(content: ReportContent) -> str:
    return json.dumps(content.as_dict(), indent=2, ensure_ascii=False, default=str)
