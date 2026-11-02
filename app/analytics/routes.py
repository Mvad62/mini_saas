import csv
import io
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.templating import Jinja2Templates

from app.analytics.service import build_survey_statistics
from app.auth.models import User
from app.config import PROJECT_ROOT
from app.database.base import get_session
from app.deps import get_current_user
from app.responses.models import Answer, Response as SurveyResponse
from app.surveys.models import Survey
from app.surveys.routes import get_owned_survey

router = APIRouter()
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
UserDependency = Annotated[User, Depends(get_current_user)]


def csv_safe_cell(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


async def build_responses_csv(
    session: AsyncSession,
    survey: Survey,
) -> str:
    questions = sorted(survey.questions, key=lambda question: question.order_index)
    responses = await session.scalars(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == survey.id)
        .options(
            selectinload(SurveyResponse.answers).selectinload(Answer.question),
            selectinload(SurveyResponse.answers).selectinload(Answer.option),
        )
        .order_by(SurveyResponse.created_at, SurveyResponse.id)
    )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["response_id", "submitted_at"]
        + [question.text for question in questions]
    )

    for response in responses:
        answers_by_question: dict[int, list[str]] = {}
        for answer in response.answers:
            if answer.option is not None:
                value = answer.option.text
            else:
                value = answer.text_value or ""
            answers_by_question.setdefault(answer.question_id, []).append(value)

        writer.writerow(
            [
                response.id,
                response.created_at.isoformat(),
                *[
                    csv_safe_cell(
                        "; ".join(answers_by_question.get(question.id, []))
                    )
                    for question in questions
                ],
            ]
        )

    return output.getvalue()


@router.get(
    "/surveys/{survey_id}/stats",
    response_class=HTMLResponse,
    name="survey_stats",
)
async def survey_stats(
    request: Request,
    survey_id: int,
    session: SessionDependency,
    current_user: UserDependency,
) -> HTMLResponse:
    survey = await get_owned_survey(session, survey_id, current_user.id)
    statistics = await build_survey_statistics(session, survey)
    return templates.TemplateResponse(
        request=request,
        name="analytics/stats.html",
        context={"survey": survey, "statistics": statistics},
    )


@router.get(
    "/surveys/{survey_id}/stats.csv",
    name="survey_stats_csv",
)
async def survey_stats_csv(
    survey_id: int,
    session: SessionDependency,
    current_user: UserDependency,
) -> StreamingResponse:
    survey = await get_owned_survey(session, survey_id, current_user.id)
    content = await build_responses_csv(session, survey)
    filename = f"survey-{survey.id}-responses.csv"
    return StreamingResponse(
        iter(("\ufeff", content)),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
