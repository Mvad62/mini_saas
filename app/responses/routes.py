import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response as HttpResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import FormData
from starlette.templating import Jinja2Templates

from app.config import PROJECT_ROOT
from app.database.base import get_session
from app.responses.models import Answer, Response as SurveyResponse
from app.responses.security import create_csrf_token, validate_csrf_token
from app.surveys.models import Option, Question, QuestionType, Survey

router = APIRouter()
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
QUESTION_FIELD = re.compile(r"^question_(\d+)$")


async def get_public_survey(session: AsyncSession, slug: str) -> Survey:
    survey = await session.scalar(
        select(Survey)
        .where(Survey.slug == slug, Survey.is_active.is_(True))
        .options(selectinload(Survey.questions).selectinload(Question.options))
    )
    if survey is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Опрос не найден или больше не доступен.",
        )
    return survey


def render_public_survey(
    request: Request,
    survey: Survey,
    *,
    errors: list[str] | None = None,
    submitted: dict[int, list[str]] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="public/survey.html",
        context={
            "survey": survey,
            "csrf_token": create_csrf_token(survey.id),
            "errors": errors or [],
            "submitted": submitted or {},
        },
        status_code=status_code,
    )


def validate_submission(
    survey: Survey,
    form_data: FormData,
) -> tuple[list[Answer], dict[int, list[str]], list[str]]:
    answers: list[Answer] = []
    submitted: dict[int, list[str]] = {}
    errors: list[str] = []
    valid_fields = {"csrf_token"}

    for question in survey.questions:
        field_name = f"question_{question.id}"
        valid_fields.add(field_name)
        values = [str(value).strip() for value in form_data.getlist(field_name)]
        submitted[question.id] = values

        if question.type == QuestionType.TEXT:
            if len(values) > 1:
                errors.append(f"Для вопроса «{question.text}» отправлено несколько ответов.")
                continue
            value = values[0] if values else ""
            if question.is_required and not value:
                errors.append(f"Заполните обязательный вопрос «{question.text}».")
            elif len(value) > 10000:
                errors.append(f"Ответ на вопрос «{question.text}» слишком длинный.")
            elif value:
                answers.append(Answer(question=question, text_value=value))
            continue

        if question.type == QuestionType.SINGLE and len(values) > 1:
            errors.append(f"Для вопроса «{question.text}» можно выбрать только один вариант.")
            continue

        if question.is_required and not values:
            errors.append(f"Выберите ответ для обязательного вопроса «{question.text}».")
            continue

        allowed_options: dict[str, Option] = {
            str(option.id): option for option in question.options
        }
        if len(values) != len(set(values)):
            errors.append(f"Для вопроса «{question.text}» один вариант выбран несколько раз.")
            continue

        selected_options = [allowed_options.get(value) for value in values]
        if any(option is None for option in selected_options):
            errors.append(f"Выбран недопустимый вариант для вопроса «{question.text}».")
            continue

        answers.extend(
            Answer(question=question, option=option)
            for option in selected_options
            if option is not None
        )

    unexpected_fields = {
        key
        for key, _ in form_data.multi_items()
        if key not in valid_fields
    }
    if unexpected_fields:
        errors.append("Форма содержит неизвестные поля. Обновите страницу и попробуйте снова.")

    return answers, submitted, errors


@router.get("/survey/{slug}", response_class=HTMLResponse, name="public_survey")
async def public_survey(
    request: Request,
    slug: str,
    session: SessionDependency,
) -> HTMLResponse:
    survey = await get_public_survey(session, slug)
    return render_public_survey(request, survey)


@router.post(
    "/survey/{slug}/submit",
    response_class=HTMLResponse,
    name="submit_survey",
)
async def submit_survey(
    request: Request,
    slug: str,
    session: SessionDependency,
) -> HttpResponse:
    survey = await get_public_survey(session, slug)
    form_data = await request.form(max_files=0, max_fields=2000)
    csrf_tokens = form_data.getlist("csrf_token")
    if (
        len(csrf_tokens) != 1
        or not isinstance(csrf_tokens[0], str)
        or not validate_csrf_token(csrf_tokens[0], survey.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Форма устарела или недействительна.",
        )

    answers, submitted, errors = validate_submission(survey, form_data)
    if errors:
        return render_public_survey(
            request,
            survey,
            errors=errors,
            submitted=submitted,
            status_code=422,
        )

    response = SurveyResponse(survey=survey, answers=answers)
    session.add(response)
    await session.commit()
    return RedirectResponse(
        url=f"/survey/{survey.slug}/thanks",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/survey/{slug}/thanks",
    response_class=HTMLResponse,
    name="survey_thanks",
)
async def survey_thanks(
    request: Request,
    slug: str,
    session: SessionDependency,
) -> HTMLResponse:
    survey = await get_public_survey(session, slug)
    return templates.TemplateResponse(
        request=request,
        name="public/thanks.html",
        context={"survey": survey},
    )
