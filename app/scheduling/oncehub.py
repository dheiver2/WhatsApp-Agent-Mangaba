"""Simple OnceHub helpers for direct scheduling via booking link."""

from app.config import get_settings


def get_booking_link() -> str:
    return get_settings().oncehub_booking_url


def get_scheduling_message(nome: str = "") -> str:
    link = get_booking_link()
    saudacao = f"{nome}, " if nome else ""
    return (
        f"{saudacao}você pode escolher o melhor dia e horário direto na nossa agenda:\n\n"
        f"{link}\n\n"
        "Assim você vê a disponibilidade atual e confirma o horário que for melhor para você."
    )
