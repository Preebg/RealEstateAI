"""Read-only share-link popover for property analysis."""

from __future__ import annotations

import streamlit as st


def render_share_popover(
    *,
    guest_mode: bool,
    share_property_id: str | None,
    from_kb: bool,
) -> None:
    """Render the share-link popover in the analysis header column."""
    from share_access import build_share_url, create_property_share_link

    if not guest_mode and share_property_id:
        with st.popover("🔗 Share with a friend"):
            st.caption(
                "Send a read-only link — no account needed. "
                "Friends can browse the portfolio but cannot save changes."
            )
            include_assumptions = st.checkbox(
                "Include my personal assumptions",
                value=True,
                help="When checked, your rent/fee sliders are shown; otherwise AI baselines only.",
            )
            if st.button("Generate share link", type="primary", key="create_share_link"):
                token = create_property_share_link(
                    str(share_property_id),
                    include_assumptions=include_assumptions,
                )
                if token:
                    st.session_state["last_share_url"] = build_share_url(token)
                else:
                    st.error("Could not create share link. Try again.")
            if st.session_state.get("last_share_url"):
                st.text_input(
                    "Copy this link",
                    value=st.session_state["last_share_url"],
                    label_visibility="collapsed",
                )
    elif not guest_mode and not from_kb:
        st.caption("Save this property to enable sharing with friends.")
