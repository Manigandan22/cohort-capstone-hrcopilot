from app.models.enums import Role
from app.services.ai.audit import redact
from app.services.ai.permissions import (
    FORBIDDEN_COLUMNS,
    PERMISSION_MATRIX,
    Access,
    Capability,
    PermissionDenied,
    UserContext,
)
from app.services.ai.policy_rag import chunk_policy_text


def _user(role: Role, user_id: int = 10, team: set[int] | None = None) -> UserContext:
    return UserContext(id=user_id, name="U", role=role, department_id=None, manager_id=None,
                       team_ids=frozenset(team or set()))


def test_matrix_covers_every_capability_for_every_role():
    for capability in Capability:
        assert set(PERMISSION_MATRIX[capability]) == set(Role)


def test_employee_cannot_decide_leave_and_gets_non_leaking_refusal():
    employee = _user(Role.EMPLOYEE)
    try:
        employee.require(Capability.DECIDE_LEAVE)
    except PermissionDenied as exc:
        assert exc.message == "You do not have permission to approve or reject leave requests."
    else:
        raise AssertionError("employee must not be able to decide leave")


def test_manager_scope_is_limited_to_self_and_direct_reports():
    manager = _user(Role.MANAGER, user_id=2, team={3, 4})
    assert manager.can_act_on_employee(Capability.DECIDE_LEAVE, 3)
    assert manager.can_act_on_employee(Capability.DECIDE_LEAVE, 2)
    assert not manager.can_act_on_employee(Capability.DECIDE_LEAVE, 99)
    assert _user(Role.ADMIN).can_act_on_employee(Capability.DECIDE_LEAVE, 99)
    assert not _user(Role.EMPLOYEE).can_act_on_employee(Capability.OTHERS_LEAVE_BALANCE, 99)


def test_sensitive_fields_are_denied_to_every_role():
    for role in Role:
        assert _user(role).access(Capability.SENSITIVE_PERSONAL) is Access.NONE
    assert {"hashed_password", "pan_number", "bank_account_number", "current_salary_usd"} <= FORBIDDEN_COLUMNS


def test_redact_removes_tokens_pan_ifsc_and_account_numbers():
    text = (
        "my PAN is ABCDE1234F, IFSC HDFC0001234, account 123456789012, "
        "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig password: hunter2"
    )
    cleaned = redact(text)
    for secret in ("ABCDE1234F", "HDFC0001234", "123456789012", "eyJhbGci", "hunter2"):
        assert secret not in cleaned
    assert "[REDACTED_PAN]" in cleaned


def test_chunking_keeps_section_labels_and_respects_size():
    text = "# Leave Policy\n\n## 1. Sick leave\n\n" + ("Sick leave is ten days. " * 80) + "\n\n## 2. Casual\n\nTwelve days."
    chunks = chunk_policy_text("Leave Policy", text, max_chars=400)
    assert len(chunks) > 2
    assert all(len(c) <= 400 for c in chunks)
    assert chunks[0].startswith("Leave Policy > 1. Sick leave")
    assert chunks[-1].startswith("Leave Policy > 2. Casual")


def test_api_embedder_keeps_input_order_and_waits_out_rate_limits(monkeypatch):
    import httpx
    from openai import RateLimitError

    from app.services.ai.embeddings import APIEmbedder

    calls = {"n": 0}

    class FakeItem:
        def __init__(self, vector):
            self.embedding = vector
            self.index = None  # Gemini leaves index empty

    class FakeEmbeddings:
        def create(self, model, input):
            calls["n"] += 1
            if calls["n"] == 1:
                response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid"))
                raise RateLimitError("quota", response=response, body=None)
            return type("R", (), {"data": [FakeItem([float(len(t)), 1.0]) for t in input]})()

    embedder = APIEmbedder("https://example.invalid/v1", "key", "fake-model", 0.6)
    embedder._client = type("C", (), {"embeddings": FakeEmbeddings()})()
    monkeypatch.setattr(APIEmbedder, "RATE_LIMIT_WAIT_SECONDS", 0)

    vectors = embedder.embed_documents(["a", "abcd"])
    assert calls["n"] == 2  # one 429, then success
    assert vectors.shape == (2, 2)
    assert vectors[1][0] > vectors[0][0]  # order preserved: longer text has the larger first component
