from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import SESSION_COOKIE_NAME, decode_session_token
from app.database.base import get_session

DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    request: Request,
    session: DatabaseSession,
) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = decode_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется войти в аккаунт.",
        )

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется войти в аккаунт.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
