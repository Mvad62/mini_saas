import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.surveys.models import Option, Question, QuestionType, Survey
from app.surveys.schemas import QuestionInput, SurveyInput

SLUG_ATTEMPTS = 5


def generate_slug() -> str:
    return secrets.token_urlsafe(8)


def question_type_from_input(value: str) -> QuestionType:
    return {
        "single_choice": QuestionType.SINGLE,
        "multiple_choice": QuestionType.MULTIPLE,
        "text": QuestionType.TEXT,
    }[value]


def replace_questions(survey: Survey, questions: list[QuestionInput]) -> None:
    survey.questions = [
        Question(
            text=question.text,
            type=question_type_from_input(question.type),
            order_index=index,
            is_required=question.is_required,
            options=[
                Option(text=option_text, order_index=option_index)
                for option_index, option_text in enumerate(question.options)
            ],
        )
        for index, question in enumerate(questions)
    ]


async def create_survey(
    session: AsyncSession,
    *,
    user_id: int,
    data: SurveyInput,
) -> Survey:
    for _ in range(SLUG_ATTEMPTS):
        slug = generate_slug()
        if await session.scalar(select(Survey.id).where(Survey.slug == slug)):
            continue

        survey = Survey(
            user_id=user_id,
            title=data.title,
            description=data.description,
            slug=slug,
        )
        replace_questions(survey, data.questions)
        session.add(survey)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            slug_exists = await session.scalar(
                select(Survey.id).where(Survey.slug == slug)
            )
            if slug_exists is not None:
                continue
            raise

        await session.commit()
        await session.refresh(survey)
        return survey

    raise RuntimeError("Не удалось сгенерировать уникальную ссылку опроса.")
