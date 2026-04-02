import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# In local development, prefer the repository .env over stale shell variables.
load_dotenv(override=True)


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    redis_url: str
    whatsapp_service_url: str
    oncehub_booking_url: str
    api_host: str
    api_port: int
    api_secret_key: str
    agent_name: str
    agent_persona: str
    max_followup_days: int
    response_timeout_seconds: int
    redis_ping_interval_seconds: int
    phone_lock_wait_seconds: int
    phone_lock_ttl_seconds: int
    message_processing_ttl_seconds: int
    message_dedup_ttl_seconds: int
    chroma_persist_dir: str
    knowledge_dir: str
    embedding_model: str

    @property
    def vectorstore_index_path(self) -> str:
        return str(Path(self.chroma_persist_dir) / "knowledge_index.json")


@lru_cache()
def get_settings() -> Settings:
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        whatsapp_service_url=os.getenv("WHATSAPP_SERVICE_URL", "http://localhost:3001"),
        oncehub_booking_url=os.getenv("ONCEHUB_BOOKING_URL", "https://oncehub.com/.ELW9PXD6B54K"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_get_env_int("API_PORT", 8000),
        api_secret_key=os.getenv("API_SECRET_KEY", "change-me"),
        agent_name=os.getenv("AGENT_NAME", "Natasha"),
        agent_persona=os.getenv(
            "AGENT_PERSONA",
            "Natasha, assistente jurídica do escritório Andrade & Lemos, feminina, carismática, acolhedora e especializada em reajuste de plano de saúde",
        ),
        max_followup_days=_get_env_int("MAX_FOLLOWUP_DAYS", 7),
        response_timeout_seconds=_get_env_int("RESPONSE_TIMEOUT_SECONDS", 300),
        redis_ping_interval_seconds=_get_env_int("REDIS_PING_INTERVAL_SECONDS", 5),
        phone_lock_wait_seconds=_get_env_int("PHONE_LOCK_WAIT_SECONDS", 120),
        phone_lock_ttl_seconds=_get_env_int("PHONE_LOCK_TTL_SECONDS", 360),
        message_processing_ttl_seconds=_get_env_int("MESSAGE_PROCESSING_TTL_SECONDS", 360),
        message_dedup_ttl_seconds=_get_env_int("MESSAGE_DEDUP_TTL_SECONDS", 86400),
        chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./data/chroma"),
        knowledge_dir=os.getenv("KNOWLEDGE_DIR", "./app/knowledge"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "keyword-tfidf-local"),
    )
