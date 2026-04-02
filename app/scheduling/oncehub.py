"""OnceHub integration for live availability and booking confirmations."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.config import get_settings


@dataclass(slots=True)
class OnceHubSlot:
    start_at: datetime
    end_at: datetime | None = None

    @property
    def iso_start(self) -> str:
        return self.start_at.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def format_display(self) -> str:
        local = self.start_at.astimezone()
        weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        return f"{weekdays[local.weekday()]}, {local.strftime('%d/%m')} às {local.strftime('%H:%M')}"


@dataclass(slots=True)
class OnceHubBookingConfirmation:
    booking_id: str
    event_type: str
    phone: str
    email: str
    invitee_name: str
    start_at: datetime | None
    end_at: datetime | None


def _settings():
    return get_settings()


def is_oncehub_configured() -> bool:
    settings = _settings()
    return bool(settings.oncehub_api_key and settings.oncehub_booking_calendar_id)


def get_booking_link() -> str:
    return _settings().oncehub_booking_url


def get_scheduling_message(nome: str = "") -> str:
    link = get_booking_link()
    saudacao = f"{nome}, é" if nome else "É"
    return (
        f"{saudacao} só clicar no link abaixo para confirmar sua consulta com o Dr. Filipe:\n\n"
        f"{link}\n\n"
        "Os horários acima refletem a disponibilidade real da agenda neste momento. "
        "Se algum deles não aparecer mais no link, escolha a opção disponível mais próxima."
    )


def format_confirmation_message(nome: str, start_at: datetime | None) -> str:
    prefix = f"{nome}, " if nome else ""
    if start_at is None:
        return (
            f"{prefix}sua consulta foi confirmada com sucesso.\n\n"
            "Se precisar ajustar algo, me avise por aqui."
        )

    slot = OnceHubSlot(start_at=start_at)
    return (
        f"{prefix}sua consulta foi confirmada para {slot.format_display()}.\n\n"
        "Se precisar ajustar algo, me avise por aqui."
    )


async def fetch_available_slots(
    preferred_at: datetime | None = None,
    limit: int = 2,
) -> list[OnceHubSlot]:
    settings = _settings()
    if not is_oncehub_configured():
        return []

    now_utc = datetime.now(UTC)
    range_start = now_utc
    if preferred_at is not None:
        preferred_utc = preferred_at.astimezone(UTC) if preferred_at.tzinfo else preferred_at.replace(tzinfo=UTC)
        if preferred_utc > now_utc:
            range_start = preferred_utc - timedelta(hours=12)
    range_end = range_start + timedelta(days=max(settings.oncehub_slot_lookahead_days, 1))

    url = f"{settings.oncehub_api_base_url.rstrip('/')}/v2/booking-calendars/{settings.oncehub_booking_calendar_id}/time-slots"
    headers = {
        "Accept": "application/json",
        "API-Key": settings.oncehub_api_key,
    }
    params = {
        "start_time": range_start.isoformat().replace("+00:00", "Z"),
        "end_time": range_end.isoformat().replace("+00:00", "Z"),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
    except Exception:
        return []

    return _extract_slots(response.json(), limit=limit)


def parse_booking_confirmation(payload: dict) -> OnceHubBookingConfirmation | None:
    event_type = str(
        payload.get("event")
        or payload.get("event_type")
        or payload.get("type")
        or ""
    ).strip()
    if event_type != "booking.scheduled":
        return None

    booking = payload.get("booking") if isinstance(payload.get("booking"), dict) else payload
    invitee = booking.get("invitee") if isinstance(booking.get("invitee"), dict) else {}
    questions = booking.get("questions_and_answers") if isinstance(booking.get("questions_and_answers"), list) else []

    phone = _extract_phone_from_payload(booking, invitee, questions)
    email = str(invitee.get("email") or booking.get("email") or "").strip()
    invitee_name = str(invitee.get("name") or booking.get("name") or "").strip()
    start_at = _parse_datetime(booking.get("start_time") or booking.get("start_at"))
    end_at = _parse_datetime(booking.get("end_time") or booking.get("end_at"))

    return OnceHubBookingConfirmation(
        booking_id=str(booking.get("id") or booking.get("booking_id") or ""),
        event_type=event_type,
        phone=phone,
        email=email,
        invitee_name=invitee_name,
        start_at=start_at,
        end_at=end_at,
    )


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = _settings().oncehub_webhook_secret
    if not secret:
        return True
    if not signature:
        return False

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidates = {
        signature.strip(),
        signature.replace("sha256=", "").strip(),
    }
    return any(hmac.compare_digest(digest, candidate) for candidate in candidates if candidate)


def _extract_slots(payload: dict, limit: int) -> list[OnceHubSlot]:
    candidates = payload.get("data") if isinstance(payload.get("data"), list) else None
    if candidates is None:
        candidates = payload.get("time_slots") if isinstance(payload.get("time_slots"), list) else None
    if candidates is None and isinstance(payload.get("data"), dict):
        nested = payload["data"]
        if isinstance(nested.get("time_slots"), list):
            candidates = nested["time_slots"]
    if candidates is None:
        candidates = []

    slots: list[OnceHubSlot] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        start_at = _parse_datetime(
            item.get("start_time")
            or item.get("start_at")
            or item.get("starting_time")
        )
        if start_at is None:
            continue
        slot = OnceHubSlot(
            start_at=start_at,
            end_at=_parse_datetime(item.get("end_time") or item.get("end_at")),
        )
        if slot.iso_start in seen:
            continue
        seen.add(slot.iso_start)
        slots.append(slot)
        if len(slots) >= limit:
            break
    return slots


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _extract_phone_from_payload(booking: dict, invitee: dict, questions: list[dict]) -> str:
    direct_candidates = [
        invitee.get("phone"),
        invitee.get("mobile_phone"),
        booking.get("phone"),
        booking.get("mobile_phone"),
    ]
    for candidate in direct_candidates:
        normalized = _normalize_phone(candidate)
        if normalized:
            return normalized

    for question in questions:
        if not isinstance(question, dict):
            continue
        label = str(question.get("label") or question.get("question") or "").lower()
        if "telefone" not in label and "phone" not in label and "whatsapp" not in label:
            continue
        answer = question.get("answer")
        normalized = _normalize_phone(answer)
        if normalized:
            return normalized
    return ""


def _normalize_phone(value: object) -> str:
    if value is None:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits


def serialize_slots(slots: list[OnceHubSlot]) -> list[dict]:
    return [{"start_at": slot.iso_start, "display": slot.format_display()} for slot in slots]


def deserialize_slots(raw_slots: list[dict] | None) -> list[str]:
    if not raw_slots:
        return []
    labels = []
    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        display = str(item.get("display") or "").strip()
        if display:
            labels.append(display)
    return labels


def booking_confirmation_to_json(confirmation: OnceHubBookingConfirmation) -> str:
    return json.dumps(
        {
            "booking_id": confirmation.booking_id,
            "event_type": confirmation.event_type,
            "phone": confirmation.phone,
            "email": confirmation.email,
            "invitee_name": confirmation.invitee_name,
            "start_at": confirmation.start_at.isoformat() if confirmation.start_at else "",
            "end_at": confirmation.end_at.isoformat() if confirmation.end_at else "",
        },
        ensure_ascii=False,
    )
