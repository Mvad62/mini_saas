import re
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.templating import Jinja2Templates

from app.auth.models import User
from app.config import PROJECT_ROOT
from app.database.base import get_session
from app.deps import get_current_user
from app.responses.models import Response as SurveyResponse
from app.surveys.models import Question, Survey
from app.surveys.schemas import QuestionInput, SurveyInput
from app.surveys.service import create_survey, replace_questions

router = APIRouter()
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
UserDependency = Annotated[User, Depends(get_current_user)]
QUESTION_FIELD = re.compile(r"^question_(\d+)_(text|type|required|options)$")


def form_template(
    request: Request,
    *,
    template_name: str,
    form: dict[str, object],
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"form": form, "errors": errors or []},
        status_code=status_code,
    )


async def parse_survey_form(request: Request) -> tuple[SurveyInput | None, dict[str, object], list[str]]:
    form_data = await request.form()
    form: dict[str, object] = {
        "title": str(form_data.get("title", "")),
        "description": str(form_data.get("description", "")),
        "questions": [],
    }

    indexed_questions: dict[int, dict[str, object]] = {}
    for key, value in form_data.multi_items():
        match = QUESTION_FIELD.fullmatch(key)
        if match is None:
            continue
        index = int(match.group(1))
        question = indexed_questions.setdefault(
            index,
            {"text": "", "type": "single_choice", "is_required": False, "options": []},
        )
        field_name = match.group(2)
        if field_name == "options":
            question["options"] = str(value).splitlines()
        elif field_name == "required":
            question["is_required"] = value == "on"
        else:
            question["type" if field_name == "type" else "text"] = str(value)

    sorted_questions = [indexed_questions[index] for index in sorted(indexed_questions)]
    form["questions"] = sorted_questions
    try:
        data = SurveyInput.model_validate(
            {
                "title": form["title"],
                "description": form["description"],
                "questions": sorted_questions,
            }
        )
    except ValidationError as error:
        messages = []
        for item in error.errors():
            location = item["loc"]
            if len(location) >= 3 and location[0] == "questions":
                question_number = int(location[1]) + 1
                messages.append(f"Вопрос {question_number}: {item['msg']}")
            else:
                messages.append(item["msg"])
        return None, form, messages
    return data, form, []


def question_form_data(survey: Survey) -> dict[str, object]:
    questions = [
        {
            "text": question.text,
            "type": {
                "single": "single_choice",
                "multiple": "multiple_choice",
                "text": "text",
            }[question.type.value],
            "is_required": question.is_required,
            "options": "\n".join(option.text for option in question.options),
        }
        for question in survey.questions
    ]
    return {
        "title": survey.title,
        "description": survey.description or "",
        "questions": questions,
    }


async def get_owned_survey(
    session: AsyncSession,
    survey_id: int,
    user_id: int,
) -> Survey:
    survey = await session.scalar(
        select(Survey)
        .where(Survey.id == survey_id, Survey.user_id == user_id)
        .options(selectinload(Survey.questions).selectinload(Question.options))
    )
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Опрос не найден.")
    return survey


def questions_match(survey: Survey, data: SurveyInput) -> bool:
    if len(survey.questions) != len(data.questions):
        return False

    type_names = {
        "single": "single_choice",
        "multiple": "multiple_choice",
        "text": "text",
    }
    for existing, submitted in zip(survey.questions, data.questions):
        if (
            existing.text != submitted.text
            or type_names[existing.type.value] != submitted.type
            or existing.is_required != submitted.is_required
            or [option.text for option in existing.options] != submitted.options
        ):
            return False
    return True


@router.get("/surveys", response_class=HTMLResponse, name="survey_list")
async def survey_list(
    request: Request,
    session: SessionDependency,
    current_user: UserDependency,
) -> HTMLResponse:
    surveys = (
        await session.scalars(
            select(Survey)
            .where(Survey.user_id == current_user.id)
            .order_by(Survey.created_at.desc(), Survey.id.desc())
        )
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="surveys/list.html",
        context={
            "surveys": surveys,
            "current_user": current_user,
            "flash_message": (
                {"type": "success", "message": "Опрос удалён."}
                if request.query_params.get("deleted") == "true"
                else None
            ),
        },
    )


@router.get("/surveys/new", response_class=HTMLResponse, name="survey_create_form")
async def survey_create_form(request: Request, current_user: UserDependency) -> HTMLResponse:
    del current_user
    return form_template(
        request,
        template_name="surveys/create.html",
        form={
            "title": "",
            "description": "",
            "questions": [
                {
                    "text": "",
                    "type": "single_choice",
                    "is_required": True,
                    "options": "Да\nНет",
                }
            ],
        },
    )


@router.post("/surveys", response_class=HTMLResponse, name="survey_create")
async def survey_create(
    request: Request,
    session: SessionDependency,
    current_user: UserDependency,
) -> Response:
    data, form, errors = await parse_survey_form(request)
    if errors or data is None:
        return form_template(
            request,
            template_name="surveys/create.html",
            form=form,
            errors=errors,
            status_code=422,
        )

    survey = await create_survey(session, user_id=current_user.id, data=data)
    return RedirectResponse(url=f"/surveys/{survey.id}/edit?created=true", status_code=303)


@router.get("/surveys/{survey_id}/edit", response_class=HTMLResponse, name="survey_edit_form")
async def survey_edit_form(
    request: Request,
    survey_id: int,
    session: SessionDependency,
    current_user: UserDependency,
    created: bool = False,
    updated: bool = False,
) -> HTMLResponse:
    survey = await get_owned_survey(session, survey_id, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="surveys/edit.html",
        context={
            "survey": survey,
            "form": question_form_data(survey),
            "errors": [],
            "created": created,
            "flash_message": (
                {
                    "type": "success",
                    "message": "Опрос создан." if created else "Изменения сохранены.",
                }
                if created or updated
                else None
            ),
        },
    )


@router.api_route(
    "/surveys/{survey_id}",
    methods=["PATCH", "POST"],
    response_class=HTMLResponse,
    name="survey_update",
)
async def survey_update(
    request: Request,
    survey_id: int,
    session: SessionDependency,
    current_user: UserDependency,
) -> Response:
    survey = await get_owned_survey(session, survey_id, current_user.id)
    data, form, errors = await parse_survey_form(request)
    template_context = {
        "survey": survey,
        "form": form,
        "errors": errors,
        "created": False,
    }
    if errors or data is None:
        return templates.TemplateResponse(
            request=request,
            name="surveys/edit.html",
            context=template_context,
            status_code=422,
        )

    response_count = await session.scalar(
        select(func.count())
        .select_from(SurveyResponse)
        .where(SurveyResponse.survey_id == survey.id)
    )
    same_questions = questions_match(survey, data)
    if response_count and not same_questions:
        return templates.TemplateResponse(
            request=request,
            name="surveys/edit.html",
            context={
                **template_context,
                "errors": [
                    "Нельзя менять опрос, на который уже поступили ответы."
                ],
            },
            status_code=409,
        )

    survey.title = data.title
    survey.description = data.description
    if not same_questions:
        replace_questions(survey, data.questions)
    await session.commit()
    return RedirectResponse(url=f"/surveys/{survey.id}/edit?updated=true", status_code=303)


@router.api_route(
    "/surveys/{survey_id}",
    methods=["DELETE"],
    name="survey_delete_api",
)
@router.api_route(
    "/surveys/{survey_id}/delete",
    methods=["POST", "DELETE"],
    name="survey_delete",
)
async def survey_delete(
    survey_id: int,
    session: SessionDependency,
    current_user: UserDependency,
) -> RedirectResponse:
    survey = await session.scalar(
        select(Survey).where(
            Survey.id == survey_id,
            Survey.user_id == current_user.id,
        )
    )
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Опрос не найден.")
    await session.delete(survey)
    await session.commit()
    return RedirectResponse(url="/surveys?deleted=true", status_code=303)
