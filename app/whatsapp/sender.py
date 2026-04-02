"""Helpers for outbound WhatsApp messages via the local WhatsApp service."""

from __future__ import annotations

import httpx

from app.config import get_settings


async def send_whatsapp_text(phone: str, message: str) -> bool:
    if not phone or not message.strip():
        return False

    settings = get_settings()
    url = f"{settings.whatsapp_service_url.rstrip('/')}/send"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json={"phone": phone, "message": message})
            response.raise_for_status()
    except Exception:
        return False

    return True
