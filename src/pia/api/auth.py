"""Authentication.

- OIDC bearer tokens (stage and prod): signature, issuer, audience, expiry, and required claims are
  verified. Teams come from a configurable claim. A principal is human only when the identity
  provider marks it so; the default is non-human, which fails safe for gates.
- API keys (dev only): refused when PIA_ENV=prod.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request

from pia.schemas import Principal


def parse_api_keys(raw: str) -> dict[str, Principal]:
    principals: dict[str, Principal] = {}
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        key, user_id, teams, kind = entry.split(":")
        principals[key] = Principal(
            user_id=user_id, teams=frozenset(t for t in teams.split("+") if t), is_human=kind == "human"
        )
    return principals


class OIDCVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        teams_claim: str = "groups",
        principal_type_claim: str = "principal_type",
        key_resolver: Callable[[str], Any] | None = None,
        jwks_url: str | None = None,
        algorithms: tuple[str, ...] = ("RS256", "ES256"),
        leeway_s: int = 30,
    ) -> None:
        if key_resolver is None:
            if not jwks_url:
                raise ValueError("jwks_url or key_resolver is required")
            client = jwt.PyJWKClient(jwks_url, cache_keys=True)
            key_resolver = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self._resolve = key_resolver
        self._issuer = issuer
        self._audience = audience
        self._teams_claim = teams_claim
        self._type_claim = principal_type_claim
        self._algorithms = list(algorithms)
        self._leeway = leeway_s

    def verify(self, token: str) -> Principal:
        claims = jwt.decode(
            token,
            self._resolve(token),
            algorithms=self._algorithms,
            audience=self._audience,
            issuer=self._issuer,
            leeway=self._leeway,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        teams = claims.get(self._teams_claim) or []
        if isinstance(teams, str):
            teams = [teams]
        return Principal(
            user_id=str(claims["sub"]),
            teams=frozenset(str(t) for t in teams),
            is_human=claims.get(self._type_claim) == "human",
        )


def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    ctx = request.app.state.ctx
    if authorization and authorization.lower().startswith("bearer "):
        if ctx.oidc is None:
            raise HTTPException(status_code=401, detail="bearer tokens are not configured")
        try:
            principal = ctx.oidc.verify(authorization[7:].strip())
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="invalid token") from exc
    elif x_api_key:
        principal = None
        for known, candidate in ctx.principals.items():
            if hmac.compare_digest(known, x_api_key):
                principal = candidate
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid API key")
    else:
        raise HTTPException(status_code=401, detail="missing credentials")

    if not ctx.limiter.allow(principal.user_id):
        ctx.metrics.inc("rate_limited_total")
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    return principal


# Backwards-compatible name
get_principal = authenticate
