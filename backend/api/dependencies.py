"""Shared FastAPI dependencies."""

from dataclasses import dataclass
from typing import Any

import aiohttp
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None
    name: str | None = None


async def get_current_user(request: Request) -> AuthUser:
    cookie = request.headers.get("cookie")
    if not cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    headers = {"cookie": cookie}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(settings.better_auth_get_session_url, headers=headers) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
                    )
                data: Any = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate session"
        ) from exc

    user = data.get("user") if isinstance(data, dict) else None
    user_id = user.get("id") if isinstance(user, dict) else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    return AuthUser(
        id=str(user_id),
        email=user.get("email") if isinstance(user.get("email"), str) else None,
        name=user.get("name") if isinstance(user.get("name"), str) else None,
    )


DbSession = Depends(get_db)
CurrentUser = Depends(get_current_user)
