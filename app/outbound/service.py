"""List-based outbound automation for Natasha."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.config import get_settings
from app.memory.user_memory import (
    add_to_history,
    get_all_active_users,
    get_stage,
    get_user_profile,
    save_user_profile,
    set_stage,
)
from app.rag.chain import generate_outbound_message
from app.whatsapp.sender import send_whatsapp_text


def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone) if ch.isdigit())


def _now() -> datetime:
    return datetime.now()


def _current_window(now: datetime) -> str | None:
    settings = get_settings()
    hour = now.hour
    if settings.outbound_morning_hour_start <= hour < settings.outbound_morning_hour_end:
        return "morning"
    if settings.outbound_evening_hour_start <= hour < settings.outbound_evening_hour_end:
        return "evening"
    return None


def _window_label(window: str, followup_day: int, attempts_total: int) -> str:
    if attempts_total == 0 and window == "morning":
        return "primeiro contato da manhã"
    if attempts_total == 0 and window == "evening":
        return "primeiro contato da noite"
    if followup_day <= 1 and window == "evening":
        return "retomada da noite"
    if window == "morning":
        return "follow-up da manhã"
    return "follow-up da noite"


def _same_day(iso_value: str, now: datetime) -> bool:
    if not iso_value:
        return False
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return False
    return parsed.date() == now.date()


def _is_outbound_profile(profile: dict) -> bool:
    return bool(profile.get("outbound_status"))


async def register_outbound_contacts(contacts: list[dict], source: str = "lista_manual") -> list[dict]:
    registered: list[dict] = []
    for item in contacts:
        phone = _normalize_phone(str(item.get("phone", "")))
        if not phone:
            continue

        profile = await get_user_profile(phone)
        if item.get("name"):
            profile["name"] = str(item["name"]).strip()
        profile["outbound_enabled"] = True
        profile["outbound_status"] = "queued"
        profile["outbound_source"] = source
        profile["outbound_notes"] = str(item.get("notes", "")).strip()
        profile["outbound_attempts_total"] = 0
        profile["outbound_last_sent_at"] = ""
        profile["outbound_last_window"] = ""
        profile["outbound_last_response_at"] = ""
        profile["lead_status"] = "outbound_pending"
        profile["ai_summary"] = "Lead importado para abordagem outbound da Natasha"

        await save_user_profile(phone, profile)
        await set_stage(phone, await get_stage(phone))

        registered.append(
            {
                "phone": phone,
                "name": profile.get("name", ""),
                "outbound_status": profile.get("outbound_status", ""),
            }
        )
    return registered


async def list_outbound_contacts() -> list[dict]:
    contacts: list[dict] = []
    for phone in await get_all_active_users():
        profile = await get_user_profile(phone)
        if not _is_outbound_profile(profile):
            continue
        contacts.append(
            {
                "phone": phone,
                "name": profile.get("name", ""),
                "lead_status": profile.get("lead_status", ""),
                "outbound_status": profile.get("outbound_status", ""),
                "outbound_enabled": bool(profile.get("outbound_enabled")),
                "outbound_attempts_total": int(profile.get("outbound_attempts_total") or 0),
                "outbound_last_sent_at": profile.get("outbound_last_sent_at", ""),
                "outbound_last_window": profile.get("outbound_last_window", ""),
                "outbound_last_response_at": profile.get("outbound_last_response_at", ""),
                "outbound_notes": profile.get("outbound_notes", ""),
            }
        )
    contacts.sort(key=lambda item: item.get("outbound_last_sent_at", ""), reverse=True)
    return contacts


async def register_outbound_reply(phone: str) -> None:
    normalized_phone = _normalize_phone(phone)
    if not normalized_phone:
        return
    profile = await get_user_profile(normalized_phone)
    if not _is_outbound_profile(profile):
        return
    profile["outbound_enabled"] = False
    profile["outbound_status"] = "responded"
    profile["outbound_last_response_at"] = _now().isoformat()
    if profile.get("lead_status") == "outbound_pending":
        profile["lead_status"] = "ai_active"
    if not profile.get("ai_summary"):
        profile["ai_summary"] = "Lead respondeu à abordagem outbound"
    await save_user_profile(normalized_phone, profile)


async def sync_outbound_state_after_stage_change(phone: str, profile: dict, stage: str) -> None:
    if not _is_outbound_profile(profile):
        return
    if stage == "confirmacao_consulta" or profile.get("lead_status") in {"scheduled", "won"}:
        profile["outbound_enabled"] = False
        profile["outbound_status"] = "scheduled" if profile.get("lead_status") == "scheduled" else "completed"
        await save_user_profile(phone, profile)


async def process_due_outbound_messages() -> dict:
    now = _now()
    window = _current_window(now)
    if window is None:
        return {"processed": 0, "sent": 0, "window": ""}

    sent = 0
    processed = 0
    for phone in await get_all_active_users():
        profile = await get_user_profile(phone)
        if not profile.get("outbound_enabled"):
            continue
        if profile.get("outbound_status") in {"responded", "scheduled", "completed", "do_not_contact"}:
            continue
        if profile.get("lead_status") in {"scheduled", "won", "waiting_human"}:
            profile["outbound_enabled"] = False
            profile["outbound_status"] = "scheduled" if profile.get("lead_status") == "scheduled" else "completed"
            await save_user_profile(phone, profile)
            continue

        last_sent_at = profile.get("outbound_last_sent_at", "")
        last_window = profile.get("outbound_last_window", "")
        if last_window == window and _same_day(last_sent_at, now):
            continue

        attempts_total = int(profile.get("outbound_attempts_total") or 0)
        followup_day = (attempts_total // 2) + 1
        if followup_day > get_settings().max_followup_days:
            profile["outbound_enabled"] = False
            profile["outbound_status"] = "completed"
            await save_user_profile(phone, profile)
            continue

        cadence_label = _window_label(window, followup_day, attempts_total)
        message = await generate_outbound_message(
            contact_name=profile.get("name", ""),
            cadence_label=cadence_label,
            followup_day=followup_day,
            notes=profile.get("outbound_notes", ""),
        )
        ok = await send_whatsapp_text(phone, message)
        processed += 1
        if not ok:
            continue

        profile["outbound_status"] = "contacted"
        profile["outbound_attempts_total"] = attempts_total + 1
        profile["outbound_last_sent_at"] = now.isoformat()
        profile["outbound_last_window"] = window
        profile["lead_status"] = "outbound_pending"
        profile["ai_summary"] = f"Outbound {window} enviado pela Natasha no dia {now.strftime('%d/%m %H:%M')}"
        await save_user_profile(phone, profile)
        await add_to_history(phone, "assistant", message)
        sent += 1

    return {"processed": processed, "sent": sent, "window": window}


async def outbound_worker() -> None:
    interval = max(get_settings().outbound_worker_interval_seconds, 30)
    while True:
        try:
            await process_due_outbound_messages()
        except Exception as exc:
            print(f"[Outbound] Worker error: {exc}")
        await asyncio.sleep(interval)
