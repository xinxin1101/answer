"""JWT authentication for trusted API identities."""

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> str:
    """Validate a signed access token and return its trusted subject."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    config: Any = request.app.state.settings
    try:
        payload = jwt.decode(
            credentials.credentials,
            config.jwt_secret,
            algorithms=["HS256"],
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id.strip()
