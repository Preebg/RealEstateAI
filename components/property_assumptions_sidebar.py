"""Sidebar assumption sliders and HITL save / override UI."""

from __future__ import annotations

from typing import Any

import streamlit as st

from authenticate import get_logged_in_user
from knowledge_base import (
    MAX_SAVED_PROPERTIES,
    compute_rent_deviation_pct,
    count_user_saved_properties,
    get_ai_baseline_maint,
    get_ai_baseline_rent,
    get_effective_display_management_fee,
    get_effective_display_maint,
    get_effective_display_rent,
    get_effective_display_vacancy,
    is_property_saved_for_user,
    is_rent_outlier,
    resolve_canonical_property_id,
    save_knowledge_base,
    save_property_to_user_account,
    save_user_property_override,
    unsave_property_from_user_account,
    user_has_override_changes,
)
from portfolio_map_page import invalidate_portfolio_cache


DOWN_PAYMENT_MODE_KEY = "down_payment_input_mode"


def _render_down_payment_input(purchase_price: float) -> tuple[float, str]:
    """Render down payment as percent or dollars; return pct and display label."""
    mode = st.session_state.get(DOWN_PAYMENT_MODE_KEY, "percent")
    purchase_price = max(float(purchase_price or 0), 0.0)

    label_col, toggle_col = st.sidebar.columns([5, 1])
    with toggle_col:
        if st.button(
            "⇄",
            key="toggle_down_payment_mode",
            help="Switch down payment between % and $",
        ):
            if mode == "percent":
                pct = float(st.session_state.get("individual_search_down_payment_pct", 25))
                st.session_state["individual_search_down_payment_dollars"] = (
                    purchase_price * pct / 100 if purchase_price > 0 else 50_000.0
                )
            else:
                dollars = float(
                    st.session_state.get(
                        "individual_search_down_payment_dollars",
                        purchase_price * 0.25 if purchase_price > 0 else 50_000.0,
                    )
                )
                if purchase_price > 0:
                    st.session_state["individual_search_down_payment_pct"] = (
                        dollars / purchase_price * 100
                    )
            st.session_state[DOWN_PAYMENT_MODE_KEY] = (
                "dollars" if mode == "percent" else "percent"
            )
            st.rerun()

    with label_col:
        if mode == "dollars":
            max_dp = purchase_price if purchase_price > 0 else 500_000.0
            if "individual_search_down_payment_dollars" not in st.session_state:
                stored_pct = float(st.session_state.get("individual_search_down_payment_pct", 25))
                st.session_state["individual_search_down_payment_dollars"] = (
                    purchase_price * stored_pct / 100 if purchase_price > 0 else 50_000.0
                )
            dollars = st.number_input(
                "Down Payment ($)",
                min_value=0.0,
                max_value=float(max_dp),
                step=1000.0,
                key="individual_search_down_payment_dollars",
            )
            pct = (dollars / purchase_price * 100) if purchase_price > 0 else 25.0
            display = f"${dollars:,.0f} ({pct:.1f}%)"
        else:
            pct = st.number_input(
                "Down Payment (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(st.session_state.get("individual_search_down_payment_pct", 25)),
                step=0.5,
                key="individual_search_down_payment_pct",
            )
            dollars = purchase_price * pct / 100 if purchase_price > 0 else 0.0
            display = f"{pct:.1f}% (${dollars:,.0f})"

    return pct, display


def render_assumption_sliders(property_info: dict[str, Any]) -> dict[str, float]:
    """
    Render AI baselines and personal assumption sliders in the sidebar.

    Returns slider values used for finance and save payloads.
    """
    original_ai_rent = get_ai_baseline_rent(property_info)
    original_ai_maint = get_ai_baseline_maint(property_info)
    ai_vacancy_baseline = float(property_info.get("ai_vacancy_rate") or 0)
    ai_mgmt_baseline = float(property_info.get("ai_management_fee") or 0)
    ai_maint_percent = get_effective_display_maint(property_info)

    st.sidebar.markdown("---")
    st.sidebar.write("### 🤖 AI Baselines (read-only)")
    st.sidebar.caption(f"Rent: ${original_ai_rent:,.0f}/mo")
    st.sidebar.caption(f"Maintenance: {original_ai_maint:.1f}%")
    st.sidebar.caption(f"Vacancy: {ai_vacancy_baseline:.1f}%")
    st.sidebar.caption(f"Management: {ai_mgmt_baseline:.1f}%")

    st.sidebar.markdown("---")
    st.sidebar.write("### 🛠️ Your Assumptions")

    rent_min, rent_max = 800.0, 4000.0
    clamped_rent = max(rent_min, min(rent_max, float(get_effective_display_rent(property_info))))
    final_monthly_rent = st.sidebar.slider(
        "Adjust Monthly Rent ($)",
        rent_min,
        rent_max,
        value=clamped_rent,
        step=25.0,
        help="The AI suggested the initial value, but you can override it here.",
    )

    maint_min, maint_max = 1.0, 15.0
    clamped_maint = max(maint_min, min(maint_max, float(ai_maint_percent)))
    final_maint_percent = st.sidebar.slider(
        "Adjust Maintenance %",
        maint_min,
        maint_max,
        value=clamped_maint,
        step=0.1,
        help="The AI suggested the initial value, but you can override it here.",
    )

    vac_min, vac_max = 1.0, 10.0
    clamped_vac = max(vac_min, min(vac_max, get_effective_display_vacancy(property_info)))
    user_vacancy_reserve = st.sidebar.slider(
        "Your Vacancy Reserve %",
        vac_min,
        vac_max,
        value=clamped_vac,
        step=0.1,
        help="Your personal vacancy assumption (AI baseline shown above).",
    )

    mgmt_min, mgmt_max = 8.0, 12.0
    clamped_mgmt = max(mgmt_min, min(mgmt_max, get_effective_display_management_fee(property_info)))
    user_management_fee = st.sidebar.slider(
        "Your Management Fee %",
        mgmt_min,
        mgmt_max,
        value=clamped_mgmt,
        step=0.1,
        help="Your personal management fee assumption (AI baseline shown above).",
    )

    closing_min, closing_max = 0.0, 10.0
    clamped_closing = max(closing_min, min(closing_max, 3.0))
    user_closing_costs_pct = st.sidebar.slider(
        "Adjust Closing Costs (%)",
        closing_min,
        closing_max,
        value=clamped_closing,
        step=0.1,
        help="Standard closing costs are around 3-5% of the purchase price.",
    )

    list_price = float(property_info.get("price") or 0)
    if list_price > 0:
        offer_min = int(list_price * 0.70)
        offer_max = int(list_price * 1.10)
        offer_default = int(list_price)
    else:
        offer_min, offer_max, offer_default = 50_000, 500_000, 200_000
    offer_default = max(offer_min, min(offer_max, offer_default))
    offer_amount = st.sidebar.slider(
        "Your Offer Amount ($)",
        float(offer_min),
        float(offer_max),
        value=float(offer_default),
        step=1000.0,
        help=(
            "Model your purchase offer — used for deal success scoring and "
            "finance metrics (mortgage, cap rate, cash on cash)."
        ),
    )

    down_payment_pct, down_payment_label = _render_down_payment_input(offer_amount)

    loan_term = st.sidebar.number_input(
        "Loan Term (yrs)",
        min_value=1,
        max_value=40,
        value=int(st.session_state.get("individual_search_loan_term", 30)),
        step=1,
        key="individual_search_loan_term",
    )
    interest_rate = st.sidebar.number_input(
        "Mortgage Rate (%)",
        min_value=0.0,
        max_value=20.0,
        value=float(st.session_state.get("individual_search_interest_rate", 6.0)),
        step=0.125,
        format="%.3f",
        key="individual_search_interest_rate",
    )

    return {
        "final_monthly_rent": final_monthly_rent,
        "final_maint_percent": final_maint_percent,
        "user_vacancy_reserve": user_vacancy_reserve,
        "user_management_fee": user_management_fee,
        "user_closing_costs_pct": user_closing_costs_pct,
        "offer_amount": offer_amount,
        "down_payment_pct": down_payment_pct,
        "down_payment_label": down_payment_label,
        "loan_term": float(loan_term),
        "interest_rate": interest_rate,
        "original_ai_rent": original_ai_rent,
        "original_ai_maint": original_ai_maint,
    }


def render_closing_costs_caption(user_closing_costs_total: float) -> None:
    st.sidebar.caption(f"Estimated Closing Costs: ${user_closing_costs_total:,.2f}")


def render_hitl_save_section(
    *,
    guest_mode: bool,
    property_info: dict[str, Any],
    address: str,
    property_id: str | None,
    from_kb: bool,
    sources: list[str],
    assumptions: dict[str, float],
    location_score: float,
    appreciation_forecast: float,
    branding_label: str,
    get_pretty_label,
) -> None:
    """Render override notes, account save, and assumption persistence controls."""
    final_monthly_rent = assumptions["final_monthly_rent"]
    final_maint_percent = assumptions["final_maint_percent"]
    user_vacancy_reserve = assumptions["user_vacancy_reserve"]
    user_management_fee = assumptions["user_management_fee"]
    original_ai_rent = assumptions["original_ai_rent"]

    has_assumption_changes = user_has_override_changes(
        property_info,
        rent=final_monthly_rent,
        maint_percent=final_maint_percent,
        vacancy_rate=user_vacancy_reserve,
        management_fee=user_management_fee,
    )

    st.divider()
    if from_kb:
        st.subheader("💾 Your Saved Assumptions")
        if property_info.get("has_user_override"):
            st.info("You have saved personal assumptions for this property.")
        else:
            st.info(
                "Shared AI property data is loaded. Adjust sliders and save "
                "**your** rent, fees, and maintenance assumptions below."
            )
    else:
        st.subheader("Improve the Algorithm")
        st.info(
            "Save this property to the shared catalog and store **your** "
            "personal underwriting assumptions."
        )
        with st.popover("View Data Sources 🔗"):
            if not sources:
                st.write("No sources found.")
            else:
                for link in set(sources):
                    pretty_name = get_pretty_label(link)
                    st.markdown(f"- [{pretty_name}]({link})")

    rent_deviation = compute_rent_deviation_pct(original_ai_rent, final_monthly_rent)
    hitl_is_outlier = is_rent_outlier(original_ai_rent, final_monthly_rent)
    if hitl_is_outlier:
        st.warning(
            f"Your rent (${final_monthly_rent:,.0f}) differs from the AI suggestion "
            f"(${original_ai_rent:,.0f}) by **{rent_deviation:.0f}%**. "
            "Please add a brief **Override Note** below so we can learn from expert judgment."
        )
    override_notes = st.text_area(
        "Override Note (required for large rent changes)",
        value=property_info.get("override_notes") or "",
        placeholder="e.g. Section 8 contract, major renovation, or comp mismatch in AI research.",
        disabled=not hitl_is_outlier,
        help="Required when your rent override is more than 50% away from the AI estimate.",
    )

    _logged_in_user = get_logged_in_user()
    _account_property_id = resolve_canonical_property_id(
        address, str(property_id) if property_id else None
    )
    _is_saved_to_account = (
        is_property_saved_for_user(_logged_in_user["id"], _account_property_id)
        if _logged_in_user and _account_property_id
        else False
    )
    _saved_count = (
        count_user_saved_properties(_logged_in_user["id"]) if _logged_in_user else 0
    )
    _at_save_limit = (
        _saved_count >= MAX_SAVED_PROPERTIES and not _is_saved_to_account
    )

    if not guest_mode:
        st.subheader("⭐ My Account")
        st.caption(f"{_saved_count} of {MAX_SAVED_PROPERTIES} properties saved")
        if _is_saved_to_account:
            st.success("This property is saved to your account.")
            if st.button("Remove from My Account", key="unsave_account_btn"):
                if _logged_in_user and _account_property_id:
                    if unsave_property_from_user_account(
                        _logged_in_user["id"], _account_property_id
                    ):
                        invalidate_portfolio_cache()
                        st.success(f"Removed {address} from your saved properties.")
                        st.rerun()
        else:
            if _at_save_limit:
                st.warning(
                    f"You have reached the limit of {MAX_SAVED_PROPERTIES} saved properties. "
                    "Remove one from the sidebar list or use **Clear all** to add another."
                )
            if st.button(
                "⭐ Save to My Account",
                type="primary",
                key="save_account_btn",
                disabled=_at_save_limit,
            ):
                if hitl_is_outlier and not str(override_notes).strip():
                    st.error(
                        "An override note is required when rent differs by more than 50% from the AI."
                    )
                    st.stop()

                if not _logged_in_user:
                    st.error("You must be signed in to save.")
                    st.stop()

                account_override_payload = {
                    "rent": final_monthly_rent,
                    "maint_percent": final_maint_percent,
                    "vacancy_rate": user_vacancy_reserve,
                    "management_fee": user_management_fee,
                    "is_outlier": hitl_is_outlier,
                    "override_notes": str(override_notes).strip(),
                }

                save_payload = None
                if not from_kb:
                    save_payload = dict(property_info)
                    save_payload["address"] = address
                    save_payload["from_kb"] = True
                    save_payload["location_score"] = location_score
                    save_payload["appreciation_forecast"] = appreciation_forecast
                    save_payload["property_category"] = branding_label
                    save_payload.update(account_override_payload)

                result_id = save_property_to_user_account(
                    _logged_in_user["id"],
                    property_id=_account_property_id,
                    property_data=save_payload,
                    override_payload=account_override_payload if from_kb else None,
                )
                if result_id is None:
                    st.error("Save failed. Check your connection and try again.")
                    st.stop()

                invalidate_portfolio_cache()
                st.success(f"Saved {address} to your account.")
                st.rerun()
    else:
        st.caption("Sign in to save properties to your personal account.")

    save_label = (
        "💾 Save My Assumptions"
        if from_kb
        else "✅ Save Property + My Assumptions"
    )
    if not guest_mode and st.button(save_label, disabled=from_kb and not has_assumption_changes):
        if hitl_is_outlier and not str(override_notes).strip():
            st.error("An override note is required when rent differs by more than 50% from the AI.")
            st.stop()

        user = get_logged_in_user()
        if not user:
            st.error("You must be signed in to save.")
            st.stop()

        override_payload = {
            "rent": final_monthly_rent,
            "maint_percent": final_maint_percent,
            "vacancy_rate": user_vacancy_reserve,
            "management_fee": user_management_fee,
            "is_outlier": hitl_is_outlier,
            "override_notes": str(override_notes).strip(),
        }

        if from_kb:
            pid = resolve_canonical_property_id(
                address, str(property_id) if property_id else None
            )
            if pid:
                result = save_user_property_override(
                    user["id"], pid, override_payload, address=address
                )
            else:
                property_info["address"] = address
                property_info["from_kb"] = True
                property_info["location_score"] = location_score
                property_info["appreciation_forecast"] = appreciation_forecast
                property_info["property_category"] = branding_label
                property_info.update(override_payload)
                result = save_knowledge_base(property_info, user_id=user["id"])
        else:
            property_info["address"] = address
            property_info["from_kb"] = True
            property_info["location_score"] = location_score
            property_info["appreciation_forecast"] = appreciation_forecast
            property_info["property_category"] = branding_label
            property_info.update(override_payload)
            result = save_knowledge_base(property_info, user_id=user["id"])

        if result is None:
            st.error("Save failed. Check your connection and try again.")
            st.stop()

        invalidate_portfolio_cache()
        st.success(
            f"Saved your assumptions for {address}."
            if from_kb
            else f"Saved {address} to the shared catalog with your assumptions."
        )
        st.rerun()
    elif guest_mode:
        st.caption("Sign in to save properties or personal assumptions to the database.")
    elif from_kb and not has_assumption_changes:
        st.caption("Adjust a slider above to enable saving your personal assumptions.")
