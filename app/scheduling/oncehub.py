"""OnceHub - link direto de agendamento."""

from app.config import get_settings


def get_booking_link() -> str:
    return get_settings().oncehub_booking_url


def get_scheduling_message(nome: str = "") -> str:
    """Mensagem de agendamento com link direto."""
    link = get_booking_link()
    saudacao = f"{nome}, é" if nome else "É"
    return (
        f"{saudacao} só clicar no link abaixo para escolher o melhor dia e horário para sua consulta com o Dr. Filipe:\n\n"
        f"{link}\n\n"
        "É rápido, simples e você consegue ver os horários disponíveis para confirmar sua consulta."
    )
