"""Vertex Brief Review Agent - Streamlit UI.

Run locally: `streamlit run streamlit_app.py`

Deployment: pushed to GitHub and connected to Streamlit Community
Cloud. The cloud app reads `ANTHROPIC_API_KEY` from Streamlit Secrets;
local dev reads it from the environment or `.streamlit/secrets.toml`.
"""

from __future__ import annotations

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

    st.title("Vertex Brief Review Agent")
    st.caption(
        "Upload a client briefing .docx. The agent runs deterministic "
        "formatting/structure checks plus Claude-powered semantic checks "
        "and returns the standard 3-column review table."
    )

    with st.sidebar:
        st.subheader("Settings")
        enable_semantic = st.toggle(
            "Run semantic checks (Claude)",
            value=True,
            help=(
                "Disable to run only the deterministic rules. Semantic "
                "checks add ~5-10s and require ANTHROPIC_API_KEY."
            ),
        )
        st.divider()
        st.subheader("Try it without a brief")
        demo_choice = st.selectbox(
            "Load a built-in demo brief",
            ["(none)", "Clean Acme brief", "Dirty Acme brief"],
        )
        st.caption(
            "These are synthetic fixtures used in the test suite. The "
            "'dirty' version intentionally violates one of every rule."
        )
        st.divider()
        st.markdown(
            "Built for the Vertex BizOps team. Source: "
            "[github.com](https://github.com)."
        )

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
    elif demo_choice and demo_choice != "(none)":
        from tests.fixtures.builder import build_clean_brief, build_dirty_brief

        if demo_choice == "Clean Acme brief":
            file_bytes = build_clean_brief()
            file_label = "demo_clean_acme.docx"
        else:
            file_bytes = build_dirty_brief()
            file_label = "demo_dirty_acme.docx"

    if file_bytes is None:
        st.info("Upload a .docx above or pick a demo from the sidebar to begin.")
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
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={col: st.column_config.TextColumn(width="medium") for col in COLUMN_HEADERS},
    )

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
