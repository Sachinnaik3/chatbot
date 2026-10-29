from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from pia import __version__
from pia.api.deps import ctx

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz(request: Request) -> dict[str, object]:
    state = ctx(request)
    return {"status": "ready", "chunks": len(state.index), "agents": state.agents.count(), "llm_model": state.llm.model}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> str:
    # Blocked at the ingress by network policy; scraped from inside the cluster only.
    return ctx(request).metrics.render()
