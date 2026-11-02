from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.templating import Jinja2Templates

from app.auth.routes import login_redirect, router as auth_router
from app.auth.models import User
from app.auth.security import SESSION_COOKIE_NAME, decode_session_token
from app.analytics.routes import router as analytics_router
from app.config import PROJECT_ROOT
from app.database.base import SessionFactory, engine
from app.database.init_db import init_db
from app.responses.routes import router as responses_router
from app.surveys.routes import router as surveys_router

templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await init_db()
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Mini SaaS для опросов", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=PROJECT_ROOT / "static"),
    name="static",
)
app.include_router(auth_router)
app.include_router(surveys_router)
app.include_router(responses_router)
app.include_router(analytics_router)


@app.get("/", include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse(url="/surveys", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def render_http_error(
    request: Request,
    error: StarletteHTTPException,
) -> HTMLResponse | JSONResponse:
    if error.status_code not in {403, 404, 422}:
        return await http_exception_handler(request, error)

    message = (
        error.detail
        if isinstance(error.detail, str)
        else "Запрос не удалось обработать."
    )
    return templates.TemplateResponse(
        request=request,
        name="errors/error.html",
        context={
            "status_code": error.status_code,
            "message": message,
            "errors": [],
            "flash_message": None,
        },
        status_code=error.status_code,
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def render_validation_error(
    request: Request,
    error: RequestValidationError,
) -> HTMLResponse:
    messages = [
        f"{'.'.join(str(part) for part in item['loc'][1:]) or 'Форма'}: {item['msg']}"
        for item in error.errors()
    ]
    return templates.TemplateResponse(
        request=request,
        name="errors/error.html",
        context={
            "status_code": 422,
            "message": "Проверьте заполнение формы и попробуйте ещё раз.",
            "errors": messages,
            "flash_message": None,
        },
        status_code=422,
    )


@app.middleware("http")
async def require_login_for_survey_pages(request: Request, call_next):
    path = request.url.path
    is_protected_page = path == "/surveys" or path.startswith("/surveys/")
    if is_protected_page:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        user_id = decode_session_token(token) if token else None
        if user_id is None:
            return login_redirect(request)
        async with SessionFactory() as session:
            user_exists = await session.scalar(
                select(User.id).where(User.id == user_id)
            )
        if user_exists is None:
            return login_redirect(request)
    return await call_next(request)


@app.get("/health")
async def health_check() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503, detail="Database is unavailable"
        ) from error

    return {"status": "ok", "database": "ok"}
