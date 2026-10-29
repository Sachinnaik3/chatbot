from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from pia.api.auth import authenticate
from pia.schemas import Principal

CurrentPrincipal = Annotated[Principal, Depends(authenticate)]


def ctx(request: Request):
    return request.app.state.ctx


def require_team(principal: Principal, *teams: str) -> None:
    if not (principal.teams & set(teams)):
        raise HTTPException(status_code=403, detail=f"requires one of: {sorted(teams)}")
