"""Report generation (JSON/HTML/PDF) with evidence references."""

from reports.builder import ReportBuilder
from reports.models import Claim, ReportContent, Section
from reports.service import GenerationResult, generate_report

__all__ = [
    "Claim",
    "GenerationResult",
    "ReportBuilder",
    "ReportContent",
    "Section",
    "generate_report",
]
