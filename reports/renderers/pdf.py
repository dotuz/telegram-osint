"""PDF renderer via fpdf2 (pure Python). Degrades gracefully if unavailable."""

from __future__ import annotations

from reports.models import ReportContent

try:
    from fpdf import FPDF

    PDF_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional dependency
    FPDF = None  # type: ignore[assignment,misc]
    PDF_AVAILABLE = False

_MAX_LINE = 600


def _latin1(text: str) -> str:
    # fpdf2 core fonts are Latin-1; replace anything outside it.
    return str(text).encode("latin-1", "replace").decode("latin-1")[:_MAX_LINE]


def _line(pdf: object, text: str, h: float = 5.0) -> None:  # noqa: ANN001
    # wrapmode="CHAR" lets fpdf break unbreakable tokens (long URLs / ids).
    pdf.multi_cell(0, h, _latin1(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")  # type: ignore[attr-defined]


def render_pdf(content: ReportContent) -> bytes:
    if not PDF_AVAILABLE:  # pragma: no cover - exercised only without fpdf2
        raise RuntimeError("PDF rendering requires the 'fpdf2' package")

    d = content.as_dict()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    _line(pdf, d["title"], h=8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120)
    _line(
        pdf,
        f"Target: {d['target'].get('value')}  |  Generated: {d['generated_at']}  |  "
        f"Report {d['report_id'][:8]}",
    )
    pdf.set_text_color(0)
    pdf.ln(2)

    for sec in d["sections"]:
        pdf.set_font("Helvetica", "B", 12)
        _line(pdf, sec["title"], h=7)
        pdf.set_font("Helvetica", "", 10)
        for claim in sec["claims"]:
            refs = (
                f"  [evidence: {', '.join(claim['evidence_refs'][:4])}]"
                if claim["evidence_refs"]
                else ""
            )
            conf = f" ({claim['confidence']}%)" if claim.get("confidence") is not None else ""
            _line(pdf, f"[{claim['assertion']}] {claim['text']}{conf}{refs}")
        _section_data(pdf, sec)
        pdf.ln(2)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120)
    _line(
        pdf,
        "Public OSINT and Telegram Bot API data only. No private Telegram content, sessions "
        "or credentials. Username matches are potential matches, not confirmed identity.",
        h=4,
    )
    return bytes(pdf.output())


def _section_data(pdf: object, sec: dict) -> None:  # noqa: ANN001
    data = sec["data"]
    for key in ("accounts", "items", "sample", "linked", "correlations"):
        rows = data.get(key)
        if not (isinstance(rows, list) and rows):
            continue
        pdf.set_font("Helvetica", "", 8)  # type: ignore[attr-defined]
        for r in rows[:30]:
            if isinstance(r, dict):
                line = " | ".join(f"{k}={v}" for k, v in r.items() if v not in (None, "", []))
                _line(pdf, "  - " + line, h=4)
        pdf.set_font("Helvetica", "", 10)  # type: ignore[attr-defined]
