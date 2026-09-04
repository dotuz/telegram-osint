"""Standalone HTML renderer -- no external dependencies, inline CSS.

All dynamic text is HTML-escaped: report content is derived from untrusted
collected material and must never inject markup.
"""

from __future__ import annotations

from html import escape

from reports.models import ReportContent, Section

_CSS = """
:root { color-scheme: light dark; }
body { font: 15px/1.55 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.6rem; margin-bottom: .2rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #8884; padding-bottom: .2rem; }
.meta { color: #888; font-size: .9rem; }
.claim { margin: .35rem 0; }
.tag { font-size: .7rem; font-weight: 700; padding: .1rem .4rem; border-radius: .3rem;
       vertical-align: middle; margin-right: .4rem; }
.FACT { background: #1a7f37; color: #fff; }
.INFERENCE { background: #9a6700; color: #fff; }
.UNKNOWN { background: #57606a; color: #fff; }
.refs { color: #888; font-size: .8rem; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; margin: .5rem 0; }
th, td { border: 1px solid #8884; padding: .3rem .5rem; text-align: left; vertical-align: top; }
code { background: #8881; padding: 0 .25rem; border-radius: .2rem; }
.disclaimer { background: #8881; padding: .75rem 1rem; border-radius: .5rem; margin-top: 2rem; }
"""


def _claims(section: Section) -> str:
    out = []
    for c in section.claims:
        refs = (
            f' <span class="refs">[evidence: {escape(", ".join(c.evidence_refs[:6]))}]</span>'
            if c.evidence_refs
            else ""
        )
        conf = f" <span class=refs>({c.confidence}%)</span>" if c.confidence is not None else ""
        out.append(
            f'<p class="claim"><span class="tag {escape(c.assertion)}">{escape(c.assertion)}</span>'
            f"{escape(c.text)}{conf}{refs}</p>"
        )
    return "\n".join(out)


def _kv_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    keys = list({k for r in rows for k in r})
    head = "".join(f"<th>{escape(k)}</th>" for k in keys)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{escape(str(r.get(k, '')))}</td>" for k in keys) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _section_html(section: Section) -> str:
    parts = [f"<h2>{escape(section.title)}</h2>", _claims(section)]
    data = section.data

    for list_key in ("accounts", "items", "sample", "linked", "correlations"):
        rows = data.get(list_key)
        if isinstance(rows, list) and rows and all(isinstance(x, dict) for x in rows):
            parts.append(_kv_table(rows))

    if section.key == "timeline" and isinstance(data.get("by_year"), dict):
        for year in sorted(data["by_year"]):
            parts.append(f"<h3>{escape(str(year))}</h3><ul>")
            for ev in data["by_year"][year][:40]:
                when = escape(str(ev.get("when", ""))[:10])
                parts.append(f"<li><code>{when}</code> {escape(str(ev.get('title', '')))}</li>")
            parts.append("</ul>")

    if section.key == "entity_graph" and isinstance(data.get("edges"), list):
        parts.append("<ul>")
        for e in data["edges"][:60]:
            parts.append(
                f"<li>{escape(str(e.get('source')))} —[{escape(str(e.get('type')))} "
                f"{e.get('confidence')}%]→ {escape(str(e.get('target')))}</li>"
            )
        parts.append("</ul>")

    return "\n".join(p for p in parts if p)


def render_html(content: ReportContent) -> str:
    d = content.as_dict()
    body = "\n".join(_section_html(Section(**_sec_kwargs(s))) for s in d["sections"])
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(d['title'])}</title><style>{_CSS}</style></head><body>"
        f"<h1>{escape(d['title'])}</h1>"
        f"<p class='meta'>Target: <code>{escape(str(d['target'].get('value')))}</code> · "
        f"Generated: {escape(d['generated_at'])} · Report {escape(d['report_id'][:8])}</p>"
        f"{body}"
        "<p class='disclaimer'>This report uses only public OSINT and Telegram Bot API data. "
        "It contains no private Telegram content and no credential/session data. Username "
        "matches are potential matches, not confirmed identity.</p>"
        "</body></html>"
    )


def _sec_kwargs(sec_dict: dict) -> dict:
    from reports.models import Claim

    return {
        "key": sec_dict["key"],
        "claims": [Claim(**c) for c in sec_dict["claims"]],
        "data": sec_dict["data"],
    }
