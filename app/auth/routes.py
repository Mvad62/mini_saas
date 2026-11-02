from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.templating import Jinja2Templates

from app.auth.models import User
from app.auth.schemas import LoginData, RegistrationData
from app.auth.security import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    generate_session_token,
    hash_password,
    verify_password,
)
from app.config import PROJECT_ROOT
from app.database.base import get_session
from app.deps import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


def validation_messages(error: ValidationError) -> list[str]:
    return [item["msg"] for item in error.errors()]


def safe_next_url(value: str | None) -> str:
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return value
    return "/surveys"


def login_template(
    request: Request,
    *,
    errors: list[str] | None = None,
    email: str = "",
    registered: bool = False,
    next_url: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "errors": errors or [],
            "email": email,
            "registered": registered,
            "next_url": next_url,
            "flash_message": (
                {"type": "success", "message": "Аккаунт создан. Теперь войдите."}
                if registered
                else None
            ),
        },
        status_code=400 if errors else 200,
    )


@router.get("/login", response_class=HTMLResponse, name="login_form")
async def login_form(request: Request, registered: bool = False) -> HTMLResponse:
    return login_template(
        request,
        registered=registered,
        next_url=request.query_params.get("next", ""),
    )


@router.get("/auth/login", response_class=HTMLResponse, include_in_schema=False)
async def auth_login_form(request: Request, registered: bool = False) -> HTMLResponse:
    return login_template(
        request,
        registered=registered,
        next_url=request.query_params.get("next", ""),
    )


@router.get("/auth/register", response_class=HTMLResponse, name="register_form")
async def register_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={"errors": [], "email": "", "name": ""},
    )


@router.post("/auth/register", response_class=HTMLResponse, name="register")
async def register(
    request: Request,
    session: AsyncSession = Depends(get_session),
    email: str = Form(),
    name: str = Form(),
    password: str = Form(),
) -> Response:
    try:
        data = RegistrationData(email=email, name=name, password=password)
    except ValidationError as error:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "errors": validation_messages(error),
                "email": email,
                "name": name,
            },
            status_code=400,
        )

    existing_user = await session.scalar(select(User.id).where(User.email == data.email))
    if existing_user is not None:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "errors": ["Пользователь с таким email уже зарегистрирован."],
                "email": data.email,
                "name": data.name,
            },
            status_code=400,
        )

    user = User(
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_user = await session.scalar(
            select(User.id).where(User.email == data.email)
        )
        if existing_user is None:
            raise
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "errors": ["Пользователь с таким email уже зарегистрирован."],
                "email": data.email,
                "name": data.name,
            },
            status_code=400,
        )

    return RedirectResponse(url="/login?registered=true", status_code=303)


@router.post("/auth/login", response_class=HTMLResponse, name="login")
async def login(
    request: Request,
    session: AsyncSession = Depends(get_session),
    email: str = Form(),
    password: str = Form(),
    next_url: str | None = Form(default=None, alias="next"),
) -> Response:
    try:
        data = LoginData(email=email, password=password)
    except ValidationError as error:
        return login_template(
            request,
            errors=validation_messages(error),
            email=email,
            next_url=next_url or "",
        )

    user = await session.scalar(select(User).where(User.email == data.email))
    if user is None or not verify_password(data.password, user.password_hash):
        return login_template(
            request,
            errors=["Неверный email или пароль."],
            email=data.email,
            next_url=next_url or "",
        )

    response = RedirectResponse(url=safe_next_url(next_url), status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=generate_session_token(user.id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.post(
    "/auth/logout",
    name="logout",
    dependencies=[Depends(get_current_user)],
)
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


def login_redirect(request: Request) -> RedirectResponse:
    destination = quote(request.url.path, safe="/")
    return RedirectResponse(url=f"/login?next={destination}", status_code=303)
