import asyncio

from app.auth import models as auth_models
from app.database.base import Base, engine
from app.responses import models as response_models
from app.surveys import models as survey_models

_ = auth_models, response_models, survey_models


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def main() -> None:
    await init_db()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
