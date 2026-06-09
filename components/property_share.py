"""Read-only share-link popover for property analysis."""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

COPY_PENDING_SHARE_URL_KEY = "_pending_clipboard_share_url"


def copy_text_to_clipboard(text: str) -> None:
    """Copy text to the browser clipboard (run at page root, not inside a popover)."""
    components.html(
        f"""
        <script>
        (function() {{
            const text = {json.dumps(text)};
            const doc = window.parent?.document || document;
            const nav = window.parent?.navigator || navigator;
            const copy = async () => {{
                if (nav?.clipboard?.writeText) {{
                    try {{
                        await nav.clipboard.writeText(text);
                        return;
                    }} catch (err) {{
                        /* fall through */
                    }}
                }}
                const ta = doc.createElement("textarea");
                ta.value = text;
                ta.setAttribute("readonly", "");
                ta.style.position = "fixed";
                ta.style.left = "-9999px";
                doc.body.appendChild(ta);
                ta.focus();
                ta.select();
                try {{
                    doc.execCommand("copy");
                }} finally {{
                    ta.remove();
                }}
            }};
            copy();
        }})();
        </script>
        """,
        height=0,
    )


def render_pending_share_clipboard_copy() -> None:
    """Run clipboard copy on the main page after the share popover closes."""
    pending = st.session_state.pop(COPY_PENDING_SHARE_URL_KEY, None)
    if pending and str(pending).strip():
        copy_text_to_clipboard(str(pending).strip())


def render_share_popover(
    *,
    guest_mode: bool,
    share_property_id: str | None,
    from_kb: bool,
    property_info: dict | None = None,
    address: str = "",
) -> None:
    """Render the share-link popover in the analysis header column."""
    from knowledge_base import persist_comps_to_canonical, persist_rent_comps_to_canonical
    from share_access import (
        build_share_url,
        create_property_share_link,
        ensure_property_saved_for_share,
        save_share_comps_snapshot,
    )

    if guest_mode:
        return

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
            if not isinstance(active_property, dict):
                st.error("No property data loaded. Analyze a property first.")
                st.stop()

            active_property = dict(active_property)
            resolved_id = ensure_property_saved_for_share(active_property, address)
            if not resolved_id:
                st.error(
                    "Could not save this property for sharing. "
                    "Use **Save Property + My Assumptions** below, then try again."
                )
                st.stop()

            active_property["id"] = resolved_id
            persist_comps_to_canonical(active_property, show_errors=True)
            persist_rent_comps_to_canonical(active_property, show_errors=True)
            token = create_property_share_link(
                resolved_id,
                include_assumptions=include_assumptions,
            )
            if token:
                share_url = build_share_url(token)
                st.session_state["last_share_url"] = share_url
                snapshot_saved = save_share_comps_snapshot(
                    token,
                    resolved_id,
                    active_property,
                )
                comps = active_property.get("comps_analysis")
                rent_comps_data = active_property.get("rent_comps_analysis")
                sales_comps = (
                    comps.get("comparable_properties")
                    if isinstance(comps, dict)
                    else None
                )
                rent_comps = (
                    rent_comps_data.get("comparable_rentals")
                    if isinstance(rent_comps_data, dict)
                    else None
                )
                if sales_comps and not snapshot_saved:
                    st.warning(
                        "Link created, but comparable sales could not be attached. "
                        "Run **Check Area Comps** again, then regenerate the link."
                    )
                elif rent_comps and not snapshot_saved:
                    st.warning(
                        "Link created, but comparable rentals could not be attached. "
                        "Run **Check Rental Comps** again, then regenerate the link."
                    )
                st.session_state[COPY_PENDING_SHARE_URL_KEY] = share_url
                copy_text_to_clipboard(share_url)
                st.session_state["property_data"] = active_property
                st.toast("Share link copied to clipboard", icon="🔗")
            else:
                st.error(
                    "Could not create share link. Sign in again or save the property, "
                    "then retry."
                )
        if st.session_state.get("last_share_url"):
            st.text_input(
                "Copy this link",
                value=st.session_state["last_share_url"],
                label_visibility="collapsed",
            )
