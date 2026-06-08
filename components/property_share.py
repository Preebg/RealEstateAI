"""Read-only share-link popover for property analysis."""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components


def _copy_text_to_clipboard(text: str) -> None:
    """Copy text to the browser clipboard (best-effort across Streamlit iframe quirks)."""
    components.html(
        f"""
        <script>
        (function() {{
            const text = {json.dumps(text)};
            const write = async () => {{
                const nav = window.parent?.navigator || navigator;
                if (nav?.clipboard?.writeText) {{
                    try {{
                        await nav.clipboard.writeText(text);
                        return;
                    }} catch (err) {{
                        /* fall through */
                    }}
                }}
                const ta = document.createElement("textarea");
                ta.value = text;
                ta.setAttribute("readonly", "");
                ta.style.position = "fixed";
                ta.style.left = "-9999px";
                (window.parent?.document || document).body.appendChild(ta);
                ta.select();
                try {{
                    (window.parent?.document || document).execCommand("copy");
                }} finally {{
                    ta.remove();
                }}
            }};
            write();
        }})();
        </script>
        """,
        height=0,
    )


def render_share_popover(
    *,
    guest_mode: bool,
    share_property_id: str | None,
    from_kb: bool,
    property_info: dict | None = None,
) -> None:
    """Render the share-link popover in the analysis header column."""
    from knowledge_base import persist_comps_to_canonical
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
                active_property = property_info
                if not isinstance(active_property, dict):
                    active_property = st.session_state.get("property_data")
                if isinstance(active_property, dict):
                    active_property = dict(active_property)
                    active_property.setdefault("id", share_property_id)
                    persist_comps_to_canonical(active_property)
                token = create_property_share_link(
                    str(share_property_id),
                    include_assumptions=include_assumptions,
                )
                if token:
                    share_url = build_share_url(token)
                    st.session_state["last_share_url"] = share_url
                    _copy_text_to_clipboard(share_url)
                    st.toast("Share link copied to clipboard", icon="🔗")
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
