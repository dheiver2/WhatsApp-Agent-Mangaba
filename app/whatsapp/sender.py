"""Helpers for outbound WhatsApp sends via the local service."""

from __future__ import annotations

import httpx

from app.config import get_settings


async def send_whatsapp_text(phone: str, message: str) -> bool:
    normalized_phone = "".join(ch for ch in str(phone) if ch.isdigit())
    if not normalized_phone or not message.strip():
        return False

    settings = get_settings()
    url = f"{settings.whatsapp_service_url.rstrip('/')}/send"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json={"phone": normalized_phone, "message": message})
            response.raise_for_status()
    except Exception:
        return False

    return True
