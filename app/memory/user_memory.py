import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from time import monotonic

import redis.asyncio as redis

from app.config import get_settings

_redis: redis.Redis | None = None
_last_ping_check = 0.0
_local_phone_locks: dict[str, asyncio.Lock] = {}
_local_phone_locks_guard = asyncio.Lock()

RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class StorageUnavailableError(RuntimeError):
    """Raised when Redis is unavailable for conversation state."""


class ConversationLockTimeoutError(RuntimeError):
    """Raised when a per-phone conversation lock cannot be acquired in time."""


def _default_profile(phone: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "phone": phone,
        "name": "",
        "operadora": "",
        "tipo_plano": "",
        "valor_antes": "",
        "valor_depois": "",
        "ano_contratacao": "",
        "beneficiarios_familia": "",
        "created_at": now,
        "last_contact": now,
        "followup_day": 0,
    }


def _user_key(phone: str) -> str:
    return f"user:{phone}"


def _history_key(phone: str) -> str:
    return f"history:{phone}"


def _stage_key(phone: str) -> str:
    return f"stage:{phone}"


def _conversation_lock_key(phone: str) -> str:
    return f"lock:conversation:{phone}"


def _message_state_key(phone: str, message_id: str) -> str:
    return f"message:{phone}:{message_id}"


async def _get_local_phone_lock(phone: str) -> asyncio.Lock:
    async with _local_phone_locks_guard:
        lock = _local_phone_locks.get(phone)
        if lock is None:
            lock = asyncio.Lock()
            _local_phone_locks[phone] = lock
        return lock


async def get_redis() -> redis.Redis:
    global _redis, _last_ping_check

    settings = get_settings()
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
        _last_ping_check = 0.0

    now = monotonic()
    if now - _last_ping_check >= settings.redis_ping_interval_seconds:
        try:
            await _redis.ping()
        except Exception as exc:  # pragma: no cover - depends on external Redis state
            _last_ping_check = 0.0
            raise StorageUnavailableError(
                f"Redis indisponível em {settings.redis_url}: {exc}"
            ) from exc
        _last_ping_check = now

    return _redis


async def ensure_storage_ready() -> None:
    await get_redis()


async def reserve_message_processing(phone: str, message_id: str) -> bool:
    """Reserve a message id before processing to avoid duplicate replies."""
    if not message_id:
        return True

    r = await get_redis()
    key = _message_state_key(phone, message_id)
    ttl = get_settings().message_processing_ttl_seconds
    reserved = await r.set(key, "processing", nx=True, ex=ttl)
    return bool(reserved)


async def mark_message_processed(phone: str, message_id: str) -> None:
    if not message_id:
        return

    r = await get_redis()
    key = _message_state_key(phone, message_id)
    await r.set(key, "processed", ex=get_settings().message_dedup_ttl_seconds)


async def release_message_processing(phone: str, message_id: str) -> None:
    if not message_id:
        return

    r = await get_redis()
    key = _message_state_key(phone, message_id)
    state = await r.get(key)
    if state == "processing":
        await r.delete(key)


async def _acquire_redis_phone_lock(phone: str) -> str:
    r = await get_redis()
    settings = get_settings()
    key = _conversation_lock_key(phone)
    token = secrets.token_hex(16)
    deadline = monotonic() + settings.phone_lock_wait_seconds

    while True:
        acquired = await r.set(key, token, nx=True, ex=settings.phone_lock_ttl_seconds)
        if acquired:
            return token
        if monotonic() >= deadline:
            raise ConversationLockTimeoutError(
                f"Tempo esgotado aguardando a conversa ativa de {phone}"
            )
        await asyncio.sleep(0.05)


async def _release_redis_phone_lock(phone: str, token: str) -> None:
    r = await get_redis()
    await r.eval(RELEASE_LOCK_SCRIPT, 1, _conversation_lock_key(phone), token)


@asynccontextmanager
async def conversation_lock(phone: str):
    """Serialize processing for a single phone across tasks and workers."""
    local_lock = await _get_local_phone_lock(phone)
    async with local_lock:
        token = await _acquire_redis_phone_lock(phone)
        try:
            yield
        finally:
            try:
                await _release_redis_phone_lock(phone, token)
            except StorageUnavailableError:
                # The Redis TTL protects us if the connection drops mid-release.
                pass


async def get_user_profile(phone: str) -> dict:
    """Get or create user profile."""
    r = await get_redis()
    data = await r.get(_user_key(phone))
    if data:
        return json.loads(data)
    return _default_profile(phone)


async def save_user_profile(phone: str, profile: dict) -> None:
    profile = dict(profile)
    profile["last_contact"] = datetime.now().isoformat()

    r = await get_redis()
    await r.set(_user_key(phone), json.dumps(profile, ensure_ascii=False))


async def get_chat_history(phone: str, limit: int = 20) -> list[dict]:
    """Get chat history for a user."""
    r = await get_redis()
    data = await r.lrange(_history_key(phone), -limit, -1)
    return [json.loads(msg) for msg in data]


async def add_to_history(phone: str, role: str, content: str) -> None:
    """Add a message to chat history."""
    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    }

    r = await get_redis()
    encoded = json.dumps(msg, ensure_ascii=False)
    await r.rpush(_history_key(phone), encoded)
    await r.ltrim(_history_key(phone), -100, -1)


async def get_stage(phone: str) -> str:
    """Get current funnel stage for user."""
    r = await get_redis()
    stage = await r.get(_stage_key(phone))
    return stage or "abordagem_inicial"


async def set_stage(phone: str, stage: str) -> None:
    r = await get_redis()
    await r.set(_stage_key(phone), stage)


async def get_all_active_users() -> list[str]:
    """Get all active user phone numbers."""
    r = await get_redis()
    keys = []
    async for key in r.scan_iter(match="user:*"):
        keys.append(key.replace("user:", ""))
    return sorted(keys)
