"""Vertex Brief Review Agent - Streamlit UI.

Run locally: `streamlit run streamlit_app.py`

Deployment: pushed to GitHub and connected to Streamlit Community
Cloud. The cloud app reads `ANTHROPIC_API_KEY` from Streamlit Secrets;
local dev reads it from the environment or `.streamlit/secrets.toml`.
"""

from __future__ import annotations

import html
import os
import time

import streamlit as st

from core.output.renderer import (
    COLUMN_HEADERS,
    summary_counts,
    to_csv,
    to_dataframe,
    to_docx,
    to_markdown,
)
from core.pipeline import run_review

_HIDE_STREAMLIT_SIDEBAR_CSS = """
<style>
/* No `st.sidebar` content — hide the empty sidebar rail and collapse control. */
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
</style>
"""

_REVIEW_TABLE_CSS = """
<style>
/* Light, high-contrast card so the table stays readable on Streamlit light or dark UI. */
.vb-review-wrap {
  overflow-x: auto;
  margin: 0.25rem 0 1rem 0;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.vb-review-table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
  font-size: 0.92rem;
  line-height: 1.55;
  background: #ffffff;
  color: #1e293b;
}
.vb-review-table thead th {
  text-align: left;
  padding: 0.7rem 0.95rem;
  font-weight: 600;
  border: 1px solid #e2e8f0;
  background: #f1f5f9;
  color: #0f172a;
  border-bottom: 2px solid #cbd5e1;
}
.vb-review-table tbody td {
  padding: 0.75rem 0.95rem;
  border: 1px solid #e8edf2;
  vertical-align: top;
  color: #334155;
}
.vb-review-table tbody tr:nth-child(odd) td { background: #fcfdfe; }
.vb-review-table tbody tr:nth-child(even) td { background: #f8fafc; }
.vb-review-table td.vb-col-section {
  font-weight: 600;
  width: 22%;
  min-width: 11rem;
  color: #0f172a;
  background: #f8fafc !important;
  border-right: 2px solid #e2e8f0;
}
.vb-review-table td.vb-col-feedback {
  font-weight: 400;
  color: #334155;
}
</style>
"""


def _review_table_html(df) -> str:
    """Build a readable HTML table; cell text is escaped, newlines preserved as <br>."""
    h0, h1, h2 = COLUMN_HEADERS

    def cell(text: object) -> str:
        return html.escape(str(text), quote=True).replace("\n", "<br>")

    head = (
        "<thead><tr>"
        f"<th>{html.escape(h0)}</th>"
        f"<th>{html.escape(h1)}</th>"
        f"<th>{html.escape(h2)}</th>"
        "</tr></thead>"
    )
    body_rows: list[str] = []
    for _, row in df.iterrows():
        body_rows.append(
            "<tr>"
            f'<td class="vb-col-section">{cell(row[h0])}</td>'
            f'<td class="vb-col-feedback">{cell(row[h1])}</td>'
            f'<td class="vb-col-feedback">{cell(row[h2])}</td>'
            "</tr>"
        )
    return (
        _REVIEW_TABLE_CSS
        + '<div class="vb-review-wrap"><table class="vb-review-table">'
        + head
        + "<tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def _bootstrap_api_key() -> None:
    """Lift the API key from Streamlit secrets into env so AnthropicClient finds it."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass


def main() -> None:
    st.set_page_config(
        page_title="Vertex Brief Review Agent",
        page_icon="V",
        layout="wide",
    )
    _bootstrap_api_key()

    st.markdown(_HIDE_STREAMLIT_SIDEBAR_CSS, unsafe_allow_html=True)

    st.title("Vertex Brief Review Agent")
    st.caption(
        "Upload a client briefing .docx. The agent runs deterministic "
        "formatting/structure checks plus Claude-powered semantic checks "
        "and returns the standard 3-column review table."
    )

    enable_semantic = True

    upload = st.file_uploader(
        "Upload a client briefing (.docx)",
        type=["docx"],
        accept_multiple_files=False,
    )

    file_bytes: bytes | None = None
    file_label: str | None = None
    if upload is not None:
        file_bytes = upload.read()
        file_label = upload.name

    if file_bytes is None:
        st.info("Upload a .docx above to begin.")
        return

    if not st.button("Run review", type="primary", use_container_width=True):
        st.write(f"Ready to review **{file_label}** ({len(file_bytes):,} bytes).")
        return

    progress = st.progress(0, text="Parsing document...")
    t0 = time.time()
    progress.progress(15, text="Parsing document...")

    outcome = run_review(file_bytes, enable_semantic=enable_semantic)
    progress.progress(95, text="Aggregating findings...")
    elapsed = time.time() - t0
    progress.progress(100, text=f"Done in {elapsed:.1f}s")
    progress.empty()

    if enable_semantic and not outcome.semantic_enabled:
        st.warning(
            "Semantic checks were skipped. "
            + (outcome.semantic_error or "No ANTHROPIC_API_KEY configured.")
        )
    elif outcome.semantic_enabled:
        st.success("Semantic checks ran. Review below.")

    counts = summary_counts(outcome.report)
    cols = st.columns(4)
    cols[0].metric("Formatting findings", counts["formatting"])
    cols[1].metric("Section findings", counts["section"])
    cols[2].metric("Missing sections", counts["missing_sections"])
    cols[3].metric(
        "Clean sections",
        f"{counts['clean_sections']}/{counts['total_sections']}",
    )

    st.subheader("Review table")
    df = to_dataframe(outcome.report)
    st.markdown(_review_table_html(df), unsafe_allow_html=True)

    st.subheader("Downloads")
    download_cols = st.columns(3)
    download_cols[0].download_button(
        "Download .docx",
        data=to_docx(outcome.report),
        file_name=f"{outcome.brief.client_name or 'brief'}_review.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )
    download_cols[1].download_button(
        "Download CSV",
        data=to_csv(outcome.report),
        file_name=f"{outcome.brief.client_name or 'brief'}_review.csv",
        mime="text/csv",
        use_container_width=True,
    )
    download_cols[2].download_button(
        "Download Markdown",
        data=to_markdown(outcome.report).encode("utf-8"),
        file_name=f"{outcome.brief.client_name or 'brief'}_review.md",
        mime="text/markdown",
        use_container_width=True,
    )

    with st.expander("Parsed sections (debug)"):
        for s in outcome.brief.sections:
            st.markdown(
                f"**{s.order:02d}. {s.title}** - "
                f"present={s.present}, tables={len(s.tables)}, "
                f"images={len(s.images)}, bullets={len(s.bullets)}"
            )
            if s.raw_text:
                st.code(s.raw_text[:600] + ("..." if len(s.raw_text) > 600 else ""))


if __name__ == "__main__":
    main()
