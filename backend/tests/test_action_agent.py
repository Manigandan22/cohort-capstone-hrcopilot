import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_audit_log import AIAuditLog
from app.models.announcement import Announcement
from app.models.leave_balance import LeaveBalance
from app.models.leave_request import LeaveRequest
from app.models.enums import LeaveRequestStatus, LeaveType
from app.models.ticket import Ticket
from app.services.ai.llm import LLMResponse, ToolCall
from tests.conftest import ADMIN, EMPLOYEE, MANAGER

URL = "/api/v1/chat/actions"


def tool(name: str, **arguments) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=arguments)])


def _leave(sync_engine, request_id):
    with Session(sync_engine) as session:
        return session.get(LeaveRequest, request_id)


def _audit(sync_engine):
    with Session(sync_engine) as session:
        return session.execute(select(AIAuditLog).order_by(AIAuditLog.id)).scalars().all()


def test_employee_applies_for_leave_through_existing_api(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("apply_leave", leave_type="sick", start_date="2026-12-01", end_date="2026-12-02", reason="Fever")]
    response = client.post(URL, json={"message": "Apply sick leave Dec 1-2, I have fever"}, headers=EMPLOYEE)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["answer"] == "Your sick leave request for 2026-12-01 to 2026-12-02 has been submitted. Status: pending approval."
    with Session(sync_engine) as session:
        created = session.execute(select(LeaveRequest).where(LeaveRequest.start_date == "2026-12-01")).scalar_one()
    assert (created.employee_id, created.status) == (3, LeaveRequestStatus.PENDING)
    row = _audit(sync_engine)[-1]
    assert (row.tool_name, row.action_status, row.records_accessed) == ("apply_leave", "COMPLETED", [f"leave_request:{created.id}"])


def test_employee_cannot_approve_leave_and_nothing_changes(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("approve_leave", request_id=1)]
    response = client.post(URL, json={"message": "Approve Employee User's leave"}, headers=EMPLOYEE)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "You do not have permission to approve or reject leave requests."
    assert _leave(sync_engine, 1).status == LeaveRequestStatus.PENDING
    assert _audit(sync_engine)[-1].action_status == "DENIED"


def test_manager_approval_requires_confirmation_then_runs_backend_logic(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("approve_leave", request_id=1)]
    proposal = client.post(URL, json={"message": "Approve Employee User's leave"}, headers=MANAGER).json()["data"]

    assert proposal["status"] == "CONFIRMATION_REQUIRED"
    assert proposal["answer"] == "Approve the pending sick leave request from Employee User for 2026-11-02 to 2026-11-03 (request #1)?"
    assert _leave(sync_engine, 1).status == LeaveRequestStatus.PENDING  # nothing happens before confirmation

    done = client.post(f"{URL}/confirm", json={"confirmation_id": proposal["confirmation_id"]}, headers=MANAGER).json()["data"]
    assert done["status"] == "COMPLETED"
    assert done["answer"] == "Leave request #1 from Employee User has been approved."
    leave = _leave(sync_engine, 1)
    assert (leave.status, leave.approver_id) == (LeaveRequestStatus.APPROVED, 2)
    with Session(sync_engine) as session:
        balance = session.execute(
            select(LeaveBalance).where(LeaveBalance.employee_id == 3, LeaveBalance.leave_type == LeaveType.SICK)
        ).scalar_one()
    assert balance.remaining == 5  # 7 - 2 days: the existing service deducted the balance

    reused = client.post(f"{URL}/confirm", json={"confirmation_id": proposal["confirmation_id"]}, headers=MANAGER)
    assert reused.status_code == 404  # one-time token


def test_confirmation_is_bound_to_the_requesting_user(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("approve_leave", request_id=1)]
    proposal = client.post(URL, json={"message": "Approve leave 1"}, headers=MANAGER).json()["data"]
    stolen = client.post(f"{URL}/confirm", json={"confirmation_id": proposal["confirmation_id"]}, headers=EMPLOYEE)
    assert stolen.status_code == 404
    assert _leave(sync_engine, 1).status == LeaveRequestStatus.PENDING


def test_cancel_does_nothing(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("create_announcement", title="Townhall moved", body="Friday's townhall is moved to 5 PM.")]
    proposal = client.post(URL, json={"message": "Announce townhall move"}, headers=MANAGER).json()["data"]
    assert proposal["answer"] == "Publish the announcement \"Townhall moved\": Friday's townhall is moved to 5 PM."
    cancelled = client.post(
        f"{URL}/confirm", json={"confirmation_id": proposal["confirmation_id"], "approve": False}, headers=MANAGER
    ).json()["data"]
    assert cancelled["status"] == "CANCELLED"
    with Session(sync_engine) as session:
        assert session.execute(select(Announcement)).scalars().all() == []


@pytest.mark.parametrize(
    "request_id, message",
    [
        (2, "You can only approve or reject leave requests from your team."),  # employee 4 reports to admin
        (3, "You can't approve or reject your own leave request."),
        (999, "You can only approve or reject leave requests from your team."),  # missing: same refusal, no leak
    ],
)
def test_manager_scope_is_enforced_before_proposing(client, fake_llm, sync_engine, request_id, message):
    fake_llm.replies = [tool("approve_leave", request_id=request_id)]
    response = client.post(URL, json={"message": "Approve it"}, headers=MANAGER)
    assert response.status_code == 403
    assert response.json()["error"]["message"] == message


def test_backend_business_rules_are_surfaced(client, fake_llm):
    # Overlaps the seeded pending request 1 for employee 3: rejected by the existing leave API.
    fake_llm.replies = [tool("apply_leave", leave_type="SICK", start_date="2026-11-03", end_date="2026-11-03", reason="Doctor")]
    response = client.post(URL, json={"message": "Sick leave Nov 3"}, headers=EMPLOYEE)
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "LEAVE_OVERLAP", "message": "A leave request already exists for overlapping dates"}


def test_invalid_arguments_are_fed_back_to_the_model(client, fake_llm):
    fake_llm.replies = [
        tool("apply_leave", leave_type="SICK", start_date="2026-12-05", end_date="2026-12-01", reason="Fever"),
        "Which dates would you like? The end date was before the start date.",
    ]
    data = client.post(URL, json={"message": "Sick leave"}, headers=EMPLOYEE).json()["data"]
    assert data["status"] == "ANSWERED"
    feedback = json.loads(fake_llm.calls[1][-1]["content"])
    assert "end_date must be on or after start_date" in feedback["error"]


def test_read_tool_result_is_given_to_the_model(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("get_my_leave_balance"), "You have 7 sick days left."]
    data = client.post(URL, json={"message": "How many sick days do I have?"}, headers=EMPLOYEE).json()["data"]
    assert data == {**data, "status": "ANSWERED", "answer": "You have 7 sick days left."}
    tool_message = fake_llm.calls[1][-1]
    assert tool_message["role"] == "tool" and '"remaining": 7.0' in tool_message["content"]
    assert _audit(sync_engine)[-1].tool_name == "get_my_leave_balance"


def test_ticket_creation(client, fake_llm, sync_engine):
    fake_llm.replies = [tool("create_ticket", title="VPN not working", description="VPN fails from home", category="it", priority="high")]
    data = client.post(URL, json={"message": "Create a high-priority IT ticket for VPN not working"}, headers=EMPLOYEE).json()["data"]
    assert data["status"] == "COMPLETED"
    with Session(sync_engine) as session:
        ticket = session.execute(select(Ticket).where(Ticket.title == "VPN not working")).scalar_one()
    assert ticket.employee_id == 3


@pytest.mark.parametrize(
    "message, status_code",
    [("Delete all leave requests.", 400), ("Show me Rahul's bank account number", 403), ("What is everyone's salary?", 403)],
)
def test_dangerous_requests_are_refused_before_the_llm(client, fake_llm, message, status_code):
    response = client.post(URL, json={"message": message}, headers=ADMIN)
    assert response.status_code == status_code
    assert fake_llm.calls == []


def test_agent_gives_up_after_too_many_steps(client, fake_llm):
    fake_llm.reply = tool("get_my_leave_balance")
    response = client.post(URL, json={"message": "loop forever"}, headers=EMPLOYEE)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_INCOMPLETE"


def test_ai_layer_never_writes_business_tables_directly():
    """Mutations must go through the existing APIs. Only the audit log is written by the AI layer."""
    ai_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "ai"
    write_patterns = re.compile(
        r"\b(db|session)\.(add|add_all|delete|merge)\("  # ORM writes through a session
        r"|\b(insert|update|delete)\(\s*[A-Z]"  # SQLAlchemy Core statements, e.g. insert(LeaveRequest)
        r"|\bINSERT\s+(OR\s+\w+\s+)?INTO\s+(?!temp\.)|\bDELETE\s+FROM\s+(?!temp\.)|\bUPDATE\s+\w+\s+SET\b",
        re.IGNORECASE,
    )
    # audit.py writes ai_audit_logs; vector_store.py writes its own separate index file.
    allowed = {"audit.py", "vector_store.py"}
    offenders = [path.name for path in ai_dir.glob("*.py") if path.name not in allowed and write_patterns.search(path.read_text())]
    assert offenders == []
