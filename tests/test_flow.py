import csv
import io
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def register_and_login(client: TestClient, *, name: str) -> str:
    email = f"{uuid4().hex}@example.com"
    response = client.post(
        "/auth/register",
        data={"email": email, "name": name, "password": "CorrectHorse123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/login?registered=true"
    assert "Аккаунт создан" in client.get("/login?registered=true").text

    response = client.post(
        "/auth/login",
        data={"email": email, "password": "CorrectHorse123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return email


def test_home_redirects_to_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/surveys"

    protected_response = client.get("/surveys", follow_redirects=False)
    assert protected_response.status_code == 303
    assert protected_response.headers["location"].startswith("/login?next=")


def test_survey_lifecycle_and_edge_cases(client: TestClient) -> None:
    register_and_login(client, name="Owner")

    empty_survey = client.post(
        "/surveys",
        data={"title": "No questions", "description": ""},
    )
    assert empty_survey.status_code == 422
    assert 'role="alert"' in empty_survey.text

    question_without_options = client.post(
        "/surveys",
        data={
            "title": "Missing options",
            "question_0_text": "Choose one",
            "question_0_type": "single_choice",
        },
    )
    assert question_without_options.status_code == 422

    too_long_title = client.post(
        "/surveys",
        data={
            "title": "T" * 201,
            "question_0_text": "Choose one",
            "question_0_type": "single_choice",
            "question_0_options": "Yes\nNo",
        },
    )
    assert too_long_title.status_code == 422

    long_question = "Question " + ("x" * 1900)
    created = client.post(
        "/surveys",
        data={
            "title": "Customer feedback " + ("x" * 180),
            "description": "End-to-end test",
            "question_0_text": long_question,
            "question_0_type": "single_choice",
            "question_0_required": "on",
            "question_0_options": "Yes\nNo",
            "question_1_text": "Which features?",
            "question_1_type": "multiple_choice",
            "question_1_options": "Speed\nReliability",
            "question_2_text": "Additional comments",
            "question_2_type": "text",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    survey_id = int(
        re.search(r"/surveys/(\d+)/edit", created.headers["location"]).group(1)
    )

    dashboard = client.get("/surveys")
    slug_match = re.search(r"/survey/([A-Za-z0-9_-]+)", dashboard.text)
    assert slug_match is not None
    slug = slug_match.group(1)
    assert f"/surveys/{survey_id}/stats" in dashboard.text

    public_client = TestClient(app)
    try:
        public_page = public_client.get(f"/survey/{slug}")
        assert public_page.status_code == 200
        assert 'type="radio"' in public_page.text
        assert 'type="checkbox"' in public_page.text
        assert "<textarea" in public_page.text
        csrf = re.search(
            r'name="csrf_token" value="([^"]+)"',
            public_page.text,
        ).group(1)
        question_ids = list(
            dict.fromkeys(re.findall(r'name="question_(\d+)"', public_page.text))
        )
        assert len(question_ids) == 3
        single_id, multiple_id, text_id = question_ids
        single_option = re.search(
            rf'<input[^>]+name="question_{single_id}"[^>]+value="(\d+)"',
            public_page.text,
        ).group(1)
        multiple_options = re.findall(
            rf'<input[^>]+name="question_{multiple_id}"[^>]+value="(\d+)"',
            public_page.text,
        )
        assert len(multiple_options) == 2

        invalid_csrf = public_client.post(
            f"/survey/{slug}/submit",
            data={"csrf_token": "invalid"},
        )
        assert invalid_csrf.status_code == 403
        assert "Ошибка 403" in invalid_csrf.text

        oversized_answer = public_client.post(
            f"/survey/{slug}/submit",
            data={
                "csrf_token": csrf,
                f"question_{single_id}": single_option,
                f"question_{multiple_id}": multiple_options[0],
                f"question_{text_id}": "x" * 10001,
            },
        )
        assert oversized_answer.status_code == 422
        assert "слишком длинный" in oversized_answer.text

        long_answer = "Long response " + ("x" * 9000)
        submission = public_client.post(
            f"/survey/{slug}/submit",
            data={
                "csrf_token": csrf,
                f"question_{single_id}": single_option,
                f"question_{multiple_id}": multiple_options,
                f"question_{text_id}": long_answer,
            },
            follow_redirects=False,
        )
        assert submission.status_code == 303
        assert submission.headers["location"] == f"/survey/{slug}/thanks"
        assert public_client.get(submission.headers["location"]).status_code == 200
    finally:
        public_client.close()

    stats = client.get(f"/surveys/{survey_id}/stats")
    assert stats.status_code == 200
    assert "<strong>1</strong>" in stats.text
    assert "Long response" in stats.text
    assert long_question in stats.text
    assert stats.text.count("<canvas") == 2

    csv_response = client.get(f"/surveys/{survey_id}/stats.csv")
    assert csv_response.status_code == 200
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    assert rows[0][2:] == [long_question, "Which features?", "Additional comments"]
    assert rows[1][3] == "Speed; Reliability"
    assert rows[1][4] == long_answer

    other_client = TestClient(app)
    try:
        register_and_login(other_client, name="Another owner")
        assert other_client.get(f"/surveys/{survey_id}/stats").status_code == 404
    finally:
        other_client.close()


def test_error_pages_and_required_form_fields(client: TestClient) -> None:
    missing_public_survey = client.get("/survey/does-not-exist")
    assert missing_public_survey.status_code == 404
    assert "Ошибка 404" in missing_public_survey.text

    missing_form_fields = client.post("/auth/register", data={})
    assert missing_form_fields.status_code == 422
    assert "Ошибка 422" in missing_form_fields.text
