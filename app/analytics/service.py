from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.responses.models import Answer, Response as SurveyResponse
from app.surveys.models import Option, Question, QuestionType, Survey

TEXT_ANSWER_LIMIT = 10
RECENT_RESPONSE_LIMIT = 20


@dataclass
class OptionStatistic:
    text: str
    response_count: int


@dataclass
class TextAnswerStatistic:
    value: str
    submitted_at: datetime


@dataclass
class QuestionStatistic:
    text: str
    question_type: QuestionType
    options: list[OptionStatistic] = field(default_factory=list)
    text_answers: list[TextAnswerStatistic] = field(default_factory=list)


@dataclass
class RecentAnswerStatistic:
    question_text: str
    value: str


@dataclass
class RecentResponseStatistic:
    submitted_at: datetime
    answers: list[RecentAnswerStatistic]


@dataclass
class SurveyStatistics:
    total_responses: int
    questions: list[QuestionStatistic]
    recent_responses: list[RecentResponseStatistic]


async def build_survey_statistics(
    session: AsyncSession,
    survey: Survey,
) -> SurveyStatistics:
    total_responses = await session.scalar(
        select(func.count(SurveyResponse.id)).where(
            SurveyResponse.survey_id == survey.id
        )
    )

    question_statistics = {
        question.id: QuestionStatistic(
            text=question.text,
            question_type=question.type,
            options=[],
            text_answers=[],
        )
        for question in survey.questions
    }

    distribution_rows = await session.execute(
        select(
            Option.id,
            Option.text,
            Question.id,
            func.count(SurveyResponse.id),
        )
        .join(Question, Question.id == Option.question_id)
        .outerjoin(Answer, Answer.option_id == Option.id)
        .outerjoin(
            SurveyResponse,
            and_(
                SurveyResponse.id == Answer.response_id,
                SurveyResponse.survey_id == survey.id,
            ),
        )
        .where(Question.survey_id == survey.id)
        .group_by(Option.id, Option.text, Question.id, Option.order_index)
        .order_by(Question.order_index, Option.order_index, Option.id)
    )
    for _, option_text, question_id, response_count in distribution_rows:
        question_statistics[question_id].options.append(
            OptionStatistic(text=option_text, response_count=response_count)
        )

    text_question_ids = [
        question.id
        for question in survey.questions
        if question.type == QuestionType.TEXT
    ]
    if text_question_ids:
        ranked_text_answers = (
            select(
                Answer.question_id.label("question_id"),
                Answer.text_value.label("text_value"),
                SurveyResponse.created_at.label("submitted_at"),
                func.row_number()
                .over(
                    partition_by=Answer.question_id,
                    order_by=(SurveyResponse.created_at.desc(), SurveyResponse.id.desc()),
                )
                .label("answer_rank"),
            )
            .join(SurveyResponse, SurveyResponse.id == Answer.response_id)
            .where(
                SurveyResponse.survey_id == survey.id,
                Answer.question_id.in_(text_question_ids),
                Answer.text_value.is_not(None),
            )
            .subquery()
        )
        text_rows = await session.execute(
            select(
                ranked_text_answers.c.question_id,
                ranked_text_answers.c.text_value,
                ranked_text_answers.c.submitted_at,
            )
            .where(ranked_text_answers.c.answer_rank <= TEXT_ANSWER_LIMIT)
            .order_by(
                ranked_text_answers.c.question_id,
                ranked_text_answers.c.answer_rank,
            )
        )
        for question_id, value, submitted_at in text_rows:
            question_statistics[question_id].text_answers.append(
                TextAnswerStatistic(value=value, submitted_at=submitted_at)
            )

    recent_response_rows = await session.scalars(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == survey.id)
        .options(
            selectinload(SurveyResponse.answers).selectinload(Answer.question),
            selectinload(SurveyResponse.answers).selectinload(Answer.option),
        )
        .order_by(SurveyResponse.created_at.desc(), SurveyResponse.id.desc())
        .limit(RECENT_RESPONSE_LIMIT)
    )
    recent_responses = []
    for response in recent_response_rows:
        answer_rows = sorted(
            response.answers,
            key=lambda answer: (
                answer.question.order_index,
                answer.id,
            ),
        )
        recent_answers = []
        for answer in answer_rows:
            if answer.option is not None:
                value = answer.option.text
            else:
                value = answer.text_value or ""
            recent_answers.append(
                RecentAnswerStatistic(
                    question_text=answer.question.text,
                    value=value,
                )
            )
        recent_responses.append(
            RecentResponseStatistic(
                submitted_at=response.created_at,
                answers=recent_answers,
            )
        )

    return SurveyStatistics(
        total_responses=total_responses or 0,
        questions=list(question_statistics.values()),
        recent_responses=recent_responses,
    )
