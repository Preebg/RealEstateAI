"""Authenticated account management (self-service delete)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import CurrentUser, get_auth_anon_client, get_auth_service_client, get_service_client
from app_logging import configure_logging, report_error
from knowledge_base import clear_all_saved_properties_from_user_account

router = APIRouter(tags=["account"])
log = configure_logging("account")


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    acknowledge: bool


class DeleteAccountResponse(BaseModel):
    ok: bool = True


def _attr_or_key(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _purge_user_rows(user_id: str) -> None:
    """Best-effort cleanup of user-owned rows before Auth user deletion."""
    clear_all_saved_properties_from_user_account(user_id, show_errors=False)
    service = get_service_client()
    if service is None:
        return
    for table in (
        "user_property_overrides",
        "recommendation_feedback",
        "property_app_views",
        "property_of_day_impressions",
        "legal_acceptances",
    ):
        try:
            service.table(table).delete().eq("user_id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            report_error(log, "account_purge_table_failed", exc, user_id=user_id, table=table)


@router.delete("/api/account", response_model=DeleteAccountResponse)
def delete_own_account(body: DeleteAccountRequest, user: CurrentUser) -> DeleteAccountResponse:
    """Verify password + email, purge app data, then delete the Auth user."""
    if not body.acknowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must acknowledge that account deletion cannot be undone.",
        )

    account_email = str(user.get("email") or "").strip().lower()
    typed_email = body.email.strip().lower()
    if not account_email or typed_email != account_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Typed email does not match the signed-in account.",
        )

    user_id = str(user["id"])
    anon = get_auth_anon_client()
    try:
        auth_response = anon.auth.sign_in_with_password(
            {"email": account_email, "password": body.password}
        )
    except Exception as exc:  # noqa: BLE001
        report_error(log, "account_delete_password_verify_failed", exc, user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        ) from exc

    signed_user = _attr_or_key(auth_response, "user")
    if signed_user is None and hasattr(auth_response, "session"):
        signed_user = _attr_or_key(getattr(auth_response, "session", None), "user")
    signed_id = str(_attr_or_key(signed_user, "id") or "")
    if not signed_id or signed_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password verification did not match this account.",
        )

    _purge_user_rows(user_id)

    admin_client = get_auth_service_client()
    if admin_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account deletion is temporarily unavailable (missing service role key).",
        )

    admin = admin_client.auth.admin
    sign_out = getattr(admin, "sign_out", None)
    if callable(sign_out):
        try:
            sign_out(user_id, "global")
        except Exception as exc:  # noqa: BLE001
            report_error(log, "account_delete_sign_out_failed", exc, user_id=user_id)

    try:
        admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        report_error(log, "account_delete_failed", exc, user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete account. Try again or contact support.",
        ) from exc

    log.info("account_deleted", user_id=user_id)
    return DeleteAccountResponse(ok=True)
