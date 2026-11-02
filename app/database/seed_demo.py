import asyncio
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_password
from app.database.base import SessionFactory, engine
from app.database.init_db import init_db
from app.responses.models import Answer, Response
from app.surveys.models import Option, Question, QuestionType, Survey

DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD") or "DemoPassword123!"
DEMO_SURVEY_SLUG = "demo-feedback"


async def seed_demo_data(session: AsyncSession) -> Survey:
    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            name="Демо-пользователь",
            password_hash=hash_password(DEMO_PASSWORD),
        )
        session.add(user)
        await session.flush()

    existing_survey = await session.scalar(
        select(Survey).where(Survey.slug == DEMO_SURVEY_SLUG)
    )
    if existing_survey is not None:
        if existing_survey.user_id != user.id:
            raise RuntimeError(
                f"Ссылка /survey/{DEMO_SURVEY_SLUG} уже занята другим опросом."
            )
        return existing_survey

    rating_question = Question(
        text="Насколько вы удовлетворены сервисом?",
        type=QuestionType.SINGLE,
        order_index=0,
        is_required=True,
        options=[
            Option(text="Очень доволен", order_index=0),
            Option(text="Нормально", order_index=1),
            Option(text="Есть проблемы", order_index=2),
        ],
    )
    feature_question = Question(
        text="Какие функции вам понравились?",
        type=QuestionType.MULTIPLE,
        order_index=1,
        is_required=True,
        options=[
            Option(text="Простой конструктор", order_index=0),
            Option(text="Графики статистики", order_index=1),
            Option(text="Экспорт CSV", order_index=2),
        ],
    )
    feedback_question = Question(
        text="Что нам стоит улучшить?",
        type=QuestionType.TEXT,
        order_index=2,
        is_required=False,
    )
    questions = [rating_question, feature_question, feedback_question]
    survey = Survey(
        user_id=user.id,
        title="Обратная связь о мини-SaaS",
        description="Демо-опрос о впечатлениях от сервиса.",
        slug=DEMO_SURVEY_SLUG,
        questions=questions,
    )
    session.add(survey)
    await session.flush()

    sample_responses = [
        (0, [0, 1], "Понравилась простота интерфейса.", 5),
        (1, [0, 2], "Добавьте возможность дублировать опрос.", 4),
        (0, [1], "Статистика стала понятнее.", 3),
        (2, [0, 1, 2], "Всё работает хорошо, спасибо!", 2),
        (0, [0, 2], "Хотелось бы больше вариантов графиков.", 1),
        (0, [0, 1], "Быстрая настройка и понятные результаты.", 0),
    ]
    for rating_index, feature_indexes, feedback, days_ago in sample_responses:
        response = Response(
            survey=survey,
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
        response.answers.append(
            Answer(
                question=rating_question,
                option=rating_question.options[rating_index],
            )
        )
        response.answers.extend(
            Answer(
                question=feature_question,
                option=feature_question.options[index],
            )
            for index in feature_indexes
        )
        if feedback:
            response.answers.append(
                Answer(question=feedback_question, text_value=feedback)
            )
        session.add(response)

    await session.flush()
    return survey


async def main() -> None:
    try:
        await init_db()
        async with SessionFactory.begin() as session:
            survey = await seed_demo_data(session)
            survey_id = survey.id
        print("Демо-опрос доступен: /survey/{0}".format(DEMO_SURVEY_SLUG))
        print(f"Статистика: /surveys/{survey_id}/stats")
        print(f"Вход: {DEMO_EMAIL}")
        print(
            "Пароль задаётся переменной DEMO_PASSWORD "
            "(для существующего аккаунта пароль не меняется)."
        )
        if DEMO_PASSWORD == "DemoPassword123!":
            print("Внимание: это демонстрационный пароль, измените его для своего окружения.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
