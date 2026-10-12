"""Test setup: an isolated SQLite DB, offline embeddings and a fake LLM. No network needed."""

import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="hrms-ai-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP / 'test.db'}",
        "JWT_SECRET_KEY": "test-secret",
        "POLICY_UPLOAD_DIR": str(_TMP / "hr-policies"),
        "EMBEDDING_BACKEND": "hash",
        "AI_INDEX_PATH": str(_TMP / "ai" / "policy_index.db"),
        "AI_WARMUP_ON_STARTUP": "false",
        "LLM_API_KEY": "",
        "LLM_BASE_URL": "https://example.invalid/v1",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401 - registers every table on Base.metadata
from app.api.v1.endpoints.chat import get_llm  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.enums import Role  # noqa: E402
from app.models.hr_policy import HRPolicy  # noqa: E402
from app.services.ai.llm import LLMError, LLMResponse  # noqa: E402

SEED_POLICY_DIR = Path(__file__).resolve().parent.parent / "seed_data" / "policies"
SYNC_DB_URL = f"sqlite:///{_TMP / 'test.db'}"


class FakeLLM:
    """Records prompts and replies with a canned response (or raises)."""

    def __init__(self):
        self.calls: list[list[dict]] = []
        self.reply: str | None = '{"sufficient": false, "answer": "", "citations": []}'
        self.error: Exception | None = None

    async def complete(self, messages, *, json_mode=False, tools=None, temperature=None):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return LLMResponse(content=self.reply)


def _seed(engine) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    upload_dir = Path(os.environ["POLICY_UPLOAD_DIR"])
    shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True)
    with Session(engine) as session:
        password = hash_password("password123")
        admin = Employee(id=1, name="Admin User", email="admin@test.dev", hashed_password=password,
                         role=Role.ADMIN, joining_date=date(2020, 1, 1))
        manager = Employee(id=2, name="Manager User", email="manager@test.dev", hashed_password=password,
                           role=Role.MANAGER, joining_date=date(2020, 1, 1), manager_id=1)
        employee = Employee(id=3, name="Employee User", email="employee@test.dev", hashed_password=password,
                            role=Role.EMPLOYEE, joining_date=date(2021, 1, 1), manager_id=2,
                            pan_number="ABCDE1234F", bank_account_number="123456789012")
        session.add_all([admin, manager, employee])
        for index, (title, category, filename) in enumerate(
            [
                ("Leave Policy", "LEAVE", "leave_policy.md"),
                ("Attendance Policy", "ATTENDANCE", "attendance_policy.md"),
                ("WFH Policy", "WFH", "wfh_policy.md"),
                ("Employee Documents Policy", "DOCUMENTS", "employee_documents_policy.md"),
            ],
            start=1,
        ):
            target = upload_dir / f"seed_policy_{index:02d}.md"
            target.write_text((SEED_POLICY_DIR / filename).read_text(encoding="utf-8"), encoding="utf-8")
            session.add(HRPolicy(title=title, category=category, original_filename=target.name,
                                 file_path=str(target), mime_type="text/markdown", checksum=f"seed-{index}"))
        session.commit()


@pytest.fixture
def sync_engine():
    engine = create_engine(SYNC_DB_URL)
    _seed(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(sync_engine, fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(user_id: int, role: Role) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id), role.value)}"}


ADMIN = auth_headers(1, Role.ADMIN)
MANAGER = auth_headers(2, Role.MANAGER)
EMPLOYEE = auth_headers(3, Role.EMPLOYEE)

__all__ = ["ADMIN", "MANAGER", "EMPLOYEE", "FakeLLM", "LLMError"]
