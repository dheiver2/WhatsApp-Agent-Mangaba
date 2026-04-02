import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from app.config import get_settings
from app.memory.user_memory import (
    ConversationLockTimeoutError,
    StorageUnavailableError,
    ensure_storage_ready,
    get_all_active_users,
    get_chat_history,
    get_stage,
    get_user_profile,
)
from app.outbound.service import (
    list_outbound_contacts,
    outbound_worker,
    process_due_outbound_messages,
    register_outbound_contacts,
)
from app.rag.vectorstore import load_knowledge_base
from app.rag.visualization import get_all_chunks, get_graph_data, search_with_details
from app.whatsapp.handlers import IncomingMessage, handle_message

STATIC_DIR = Path(__file__).parent / "static"


def _json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status_code)


def _safe_parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_lead_item(phone: str, profile: dict, stage: str) -> dict:
    return {
        "phone": phone,
        "name": profile.get("name", ""),
        "stage": stage,
        "lead_status": profile.get("lead_status", "ai_active"),
        "outbound_status": profile.get("outbound_status", ""),
        "operadora": profile.get("operadora", ""),
        "last_contact": profile.get("last_contact", ""),
        "handoff_requested": bool(profile.get("handoff_requested")),
        "handoff_reason": profile.get("handoff_reason", ""),
        "handoff_updated_at": profile.get("handoff_updated_at", ""),
        "ai_summary": profile.get("ai_summary", ""),
    }


async def _collect_leads() -> list[dict]:
    phones = await get_all_active_users()
    leads = []
    for phone in phones:
        profile = await get_user_profile(phone)
        stage = await get_stage(phone)
        leads.append(_build_lead_item(phone, profile, stage))
    leads.sort(key=lambda item: item.get("last_contact", ""), reverse=True)
    return leads


def _parse_float(value: str | None, default: float, minimum: float, maximum: float) -> float:
    if value is None or value == "":
        return default
    parsed = float(value)
    return min(max(parsed, minimum), maximum)


def _parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    parsed = int(value)
    return min(max(parsed, minimum), maximum)


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize the knowledge base on startup."""
    print("[Startup] Checking Redis...")
    await ensure_storage_ready()
    print("[Startup] Redis ready.")
    print("[Startup] Loading knowledge base...")
    load_knowledge_base()
    print("[Startup] Ready to receive messages!")
    outbound_task = asyncio.create_task(outbound_worker())
    yield
    outbound_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await outbound_task
    print("[Shutdown] Cleaning up...")


async def process_message(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _json_error("Invalid JSON payload", 400)

    try:
        message = IncomingMessage.from_payload(payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    settings = get_settings()
    try:
        result = await asyncio.wait_for(
            handle_message(message),
            timeout=settings.response_timeout_seconds,
        )
        return JSONResponse(result.to_dict())
    except ConversationLockTimeoutError as exc:
        return _json_error(str(exc), 409)
    except StorageUnavailableError as exc:
        return _json_error(str(exc), 503)
    except asyncio.TimeoutError:
        return _json_error("Response generation timed out", 504)
    except Exception as exc:
        print(f"[Error] Message processing failed: {exc}")
        return _json_error(str(exc), 500)


async def health(_request: Request) -> JSONResponse:
    try:
        await ensure_storage_ready()
    except StorageUnavailableError as exc:
        return JSONResponse(
            {
                "status": "degraded",
                "service": "whatsapp-agent-api",
                "storage": "unavailable",
                "detail": str(exc),
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "ok",
            "service": "whatsapp-agent-api",
            "storage": "redis",
        }
    )


async def list_leads(_request: Request) -> JSONResponse:
    leads = await _collect_leads()
    return JSONResponse({"leads": leads, "total": len(leads)})


async def get_lead(request: Request) -> JSONResponse:
    phone = request.path_params["phone"]
    profile = await get_user_profile(phone)
    stage = await get_stage(phone)

    history = await get_chat_history(phone, limit=50)
    return JSONResponse(
        {
            "profile": profile,
            "stage": stage,
            "lead_status": profile.get("lead_status", "ai_active"),
            "ai_summary": profile.get("ai_summary", ""),
            "history": history,
        }
    )


async def ops_summary(_request: Request) -> JSONResponse:
    leads = await _collect_leads()
    stage_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    stale_cutoff = datetime.now() - timedelta(hours=24)
    stale_leads = 0

    for lead in leads:
        stage = lead["stage"]
        status = lead["lead_status"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1

        last_contact = _safe_parse_iso(lead.get("last_contact", ""))
        if last_contact and last_contact < stale_cutoff and status not in {"scheduled", "won"}:
            stale_leads += 1

    return JSONResponse(
        {
            "total_leads": len(leads),
            "waiting_human": status_counts.get("waiting_human", 0),
            "scheduled": status_counts.get("scheduled", 0),
            "won": status_counts.get("won", 0),
            "stale_leads": stale_leads,
            "status_counts": status_counts,
            "stage_counts": stage_counts,
        }
    )


async def list_outbound(_request: Request) -> JSONResponse:
    contacts = await list_outbound_contacts()
    return JSONResponse({"contacts": contacts, "total": len(contacts)})


async def import_outbound_contacts(request: Request) -> JSONResponse:
    payload = await request.json()
    contacts = payload.get("contacts")
    if not isinstance(contacts, list) or not contacts:
        return _json_error("Field 'contacts' must be a non-empty list", 400)

    registered = await register_outbound_contacts(contacts)
    return JSONResponse({"registered": registered, "total": len(registered)})


async def run_outbound(_request: Request) -> JSONResponse:
    result = await process_due_outbound_messages()
    return JSONResponse(result)


async def knowledge_chunks(_request: Request) -> JSONResponse:
    chunks = get_all_chunks()
    return JSONResponse({"chunks": chunks, "total": len(chunks)})


async def knowledge_graph(request: Request) -> JSONResponse:
    try:
        threshold = _parse_float(
            request.query_params.get("threshold"),
            default=0.55,
            minimum=0.1,
            maximum=0.99,
        )
    except ValueError:
        return _json_error("Query parameter 'threshold' must be numeric", 400)
    return JSONResponse(get_graph_data(similarity_threshold=threshold))


async def knowledge_search(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "").strip()
    if len(query) < 2:
        return _json_error("Query parameter 'q' must have at least 2 characters", 400)

    try:
        top_k = _parse_int(
            request.query_params.get("top_k"),
            default=5,
            minimum=1,
            maximum=20,
        )
    except ValueError:
        return _json_error("Query parameter 'top_k' must be an integer", 400)

    return JSONResponse(search_with_details(query=query, top_k=top_k))


async def dashboard(_request: Request) -> HTMLResponse:
    html_path = STATIC_DIR / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


routes = [
    Route("/api/v1/message", process_message, methods=["POST"]),
    Route("/api/v1/health", health, methods=["GET"]),
    Route("/api/v1/leads", list_leads, methods=["GET"]),
    Route("/api/v1/leads/{phone:str}", get_lead, methods=["GET"]),
    Route("/api/v1/ops/summary", ops_summary, methods=["GET"]),
    Route("/api/v1/outbound/contacts", list_outbound, methods=["GET"]),
    Route("/api/v1/outbound/contacts", import_outbound_contacts, methods=["POST"]),
    Route("/api/v1/outbound/run", run_outbound, methods=["POST"]),
    Route("/api/v1/knowledge/chunks", knowledge_chunks, methods=["GET"]),
    Route("/api/v1/knowledge/graph", knowledge_graph, methods=["GET"]),
    Route("/api/v1/knowledge/search", knowledge_search, methods=["GET"]),
    Route("/dashboard", dashboard, methods=["GET"]),
]

app = Starlette(debug=False, routes=routes, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
