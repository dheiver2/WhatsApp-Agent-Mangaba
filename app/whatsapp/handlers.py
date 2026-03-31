"""WhatsApp message handler - bridge between HTTP API and the agent."""

from dataclasses import dataclass

from app.agents.attendant import AttendantAgent
from app.memory.user_memory import (
    conversation_lock,
    mark_message_processed,
    release_message_processing,
    reserve_message_processing,
)

_agent: AttendantAgent | None = None


def get_agent() -> AttendantAgent:
    global _agent
    if _agent is None:
        _agent = AttendantAgent()
    return _agent


@dataclass(slots=True)
class IncomingMessage:
    phone: str
    name: str = ""
    text: str = ""
    message_id: str = ""
    timestamp: int | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "IncomingMessage":
        phone = str(payload.get("phone", "")).strip()
        text = str(payload.get("text", "")).strip()
        if not phone:
            raise ValueError("Field 'phone' is required")
        if not text:
            raise ValueError("Field 'text' is required")

        raw_timestamp = payload.get("timestamp")
        if raw_timestamp in {None, ""}:
            timestamp = None
        else:
            try:
                timestamp = int(raw_timestamp)
            except (TypeError, ValueError) as exc:
                raise ValueError("Field 'timestamp' must be an integer") from exc

        return cls(
            phone=phone,
            name=str(payload.get("name", "")).strip(),
            text=text,
            message_id=str(payload.get("message_id", "")).strip(),
            timestamp=timestamp,
        )


@dataclass(slots=True)
class OutgoingMessage:
    reply: str
    stage: str = ""
    intent: str = ""
    duplicate: bool = False

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "stage": self.stage,
            "intent": self.intent,
            "duplicate": self.duplicate,
        }


async def handle_message(msg: IncomingMessage) -> OutgoingMessage:
    """Process an incoming message and return the agent's reply."""
    agent = get_agent()

    phone = msg.phone.replace("@s.whatsapp.net", "").strip()
    reserved = await reserve_message_processing(phone, msg.message_id)
    if not reserved:
        return OutgoingMessage(reply="", duplicate=True)

    try:
        async with conversation_lock(phone):
            reply = await agent.process_message(
                phone=phone,
                name=msg.name,
                text=msg.text,
            )
        await mark_message_processed(phone, msg.message_id)
    except Exception:
        await release_message_processing(phone, msg.message_id)
        raise

    return OutgoingMessage(reply=reply)
