from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionKind = Literal["single_choice", "multiple_choice", "text"]


class QuestionInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    type: QuestionKind
    is_required: bool = True
    options: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("options")
    @classmethod
    def normalize_options(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if any(len(value) > 500 for value in normalized):
            raise ValueError("Вариант ответа не должен быть длиннее 500 символов.")
        return normalized

    @model_validator(mode="after")
    def validate_options(self) -> "QuestionInput":
        if self.type == "text":
            self.options = []
            return self
        if len(self.options) < 2:
            raise ValueError("Для вопроса с выбором добавьте не менее двух вариантов.")
        normalized = [option.casefold() for option in self.options]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Варианты ответа не должны повторяться.")
        return self


class SurveyInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    questions: list[QuestionInput] = Field(min_length=1, max_length=50)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
