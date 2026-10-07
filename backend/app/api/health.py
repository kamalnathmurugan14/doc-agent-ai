from fastapi import APIRouter, Request

from app.config import APP_VERSION

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    c = request.app.state.container
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ollama": await c.llm.ping(),
        "model": c.llm.model,
        "retriever": {"name": c.retriever.name, "ok": await c.retriever.ping()},
        "classifier": {"name": c.classifier.name, "ok": await c.classifier.ping()},
        "require_approval": sorted(c.settings.approval_kinds),
    }
