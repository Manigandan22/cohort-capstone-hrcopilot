"""HR action tools. Every tool that changes data calls an EXISTING CB Nest API route with the
current user's own bearer token, so the backend's validation, role checks and business rules
stay the source of truth. Nothing here writes to the database directly.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.services.ai.permissions import Capability, PermissionDenied, UserContext

# --------------------------------------------------------------------------- HTTP client


class BackendAPIError(Exception):
    """A non-2xx response from an existing API. ``message`` is the backend's own user-facing text."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"{status_code} {code}: {message}")


class HRApiClient:
    """Calls the existing /api/v1 routes as the current user.

    By default requests go through the FastAPI app in-process (httpx ASGI transport): the full
    stack still runs (routing, auth dependency, validation, business rules) without a network
    hop. Set AI_INTERNAL_API_BASE_URL to send real HTTP requests instead.
    """

    def __init__(self, access_token: str):
        headers = {"Authorization": f"Bearer {access_token}"}
        if settings.ai_internal_api_base_url:
            self._client = httpx.AsyncClient(base_url=settings.ai_internal_api_base_url, headers=headers, timeout=20)
        else:
            from app.main import app  # Imported lazily to avoid an import cycle.

            self._client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://cbnest.internal", headers=headers, timeout=20
            )

    async def __aenter__(self) -> "HRApiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> Any:
        response = await self._client.request(method, f"/api/v1{path}", json=json, params=params)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_success:
            return body.get("data") if isinstance(body, dict) else body
        raise _api_error(response.status_code, body)


def _api_error(status_code: int, body: Any) -> BackendAPIError:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):  # error_response(...) envelope
        return BackendAPIError(status_code, detail["error"].get("code", "ERROR"), detail["error"].get("message", ""))
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return BackendAPIError(status_code, body["error"].get("code", "ERROR"), body["error"].get("message", ""))
    if isinstance(detail, list) and detail:  # FastAPI request validation errors
        first = detail[0]
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        return BackendAPIError(status_code, "VALIDATION_ERROR", f"{field}: {first.get('msg', 'invalid value')}".strip(": "))
    if isinstance(detail, str):
        return BackendAPIError(status_code, "ERROR", detail)
    return BackendAPIError(status_code, "ERROR", "The request could not be completed.")


# --------------------------------------------------------------------------- tool arguments


class NoArgs(BaseModel):
    pass


class SearchEmployeesArgs(BaseModel):
    query: str = Field(min_length=2, max_length=120)


class ApplyLeaveArgs(BaseModel):
    leave_type: Literal["CASUAL", "SICK", "EARNED"]
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=500)
    is_half_day: bool = False
    half_day_period: Literal["FIRST_HALF", "SECOND_HALF"] | None = None

    @field_validator("leave_type", "half_day_period", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) and value.strip() else (None if value == "" else value)

    @model_validator(mode="after")
    def _check(self) -> "ApplyLeaveArgs":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.is_half_day and self.start_date != self.end_date:
            raise ValueError("a half-day leave must start and end on the same date")
        if self.is_half_day and self.half_day_period is None:
            raise ValueError("half_day_period (FIRST_HALF or SECOND_HALF) is required for a half-day leave")
        if not self.is_half_day:
            self.half_day_period = None
        return self


class LeaveDecisionArgs(BaseModel):
    request_id: int = Field(gt=0)


class CreateTicketArgs(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=5, max_length=5000)
    category: Literal["IT", "HR", "ONBOARDING"]
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"

    @field_validator("category", "priority", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class AssignTicketArgs(BaseModel):
    ticket_id: int = Field(gt=0)
    assignee_id: int = Field(gt=0)


class TicketStatusArgs(BaseModel):
    ticket_id: int = Field(gt=0)
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED"]

    @field_validator("status", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper().replace(" ", "_") if isinstance(value, str) else value


class AnnouncementArgs(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    body: str = Field(min_length=5, max_length=5000)


class AssignProjectArgs(BaseModel):
    employee_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    role_on_project: str | None = Field(default=None, min_length=2, max_length=120)


class CreateProjectArgs(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["ONGOING", "COMPLETED", "ON_HOLD", "PLANNED"] = "ONGOING"

    @field_validator("status", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper().replace(" ", "_") if isinstance(value, str) else value


# --------------------------------------------------------------------------- tool registry


@dataclass
class ToolContext:
    user: UserContext
    api: HRApiClient
    db: AsyncSession


@dataclass
class ToolOutcome:
    data: Any
    # Deterministic, user-facing summary for actions (no LLM involved).
    summary: str | None = None
    records: tuple[str, ...] = ()


Handler = Callable[[ToolContext, BaseModel], Awaitable[ToolOutcome]]
Describer = Callable[[ToolContext, BaseModel], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    args_model: type[BaseModel]
    capability: Capability
    handler: Handler
    mutates: bool = False
    # High-impact actions are proposed first and only run after the user confirms.
    requires_confirmation: bool = False
    describe: Describer | None = None

    def openai_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def parse_args(self, raw: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(raw or {})


def _props(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_STR = {"type": "string"}
_INT = {"type": "integer"}


async def _employee_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(ids)))).all()
    # End the read transaction so the API call that follows can take SQLite's write lock.
    await db.commit()
    return dict(rows)


# ---- read tools


async def _get_my_leave_balance(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    return ToolOutcome(await ctx.api.request("GET", "/leaves/balances/me"))


async def _get_my_leave_requests(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    data = await ctx.api.request("GET", "/leaves/requests/me", params={"limit": 20})
    return ToolOutcome(data.get("items", []))


async def _get_my_tickets(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    data = await ctx.api.request("GET", "/tickets", params={"mine": "true", "limit": 20})
    items = [{k: t.get(k) for k in ("id", "title", "category", "priority", "status", "assignee_id")} for t in data.get("items", [])]
    return ToolOutcome(items)


async def _list_pending_leave_requests(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    data = await ctx.api.request("GET", "/leaves/requests/pending", params={"limit": 50})
    items = [i for i in data.get("items", []) if ctx.user.can_act_on_employee(Capability.DECIDE_LEAVE, i["employee_id"])]
    names = await _employee_names(ctx.db, {i["employee_id"] for i in items})
    return ToolOutcome(
        [
            {
                "request_id": i["id"],
                "employee_name": names.get(i["employee_id"], "Unknown"),
                "leave_type": i["leave_type"],
                "start_date": i["start_date"],
                "end_date": i["end_date"],
                "is_half_day": i["is_half_day"],
                "reason": i["reason"],
            }
            for i in items
        ]
    )


async def _list_open_tickets(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    data = await ctx.api.request("GET", "/tickets", params={"limit": 50})
    items = [t for t in data.get("items", []) if t.get("status") != "RESOLVED"]
    names = await _employee_names(ctx.db, {t["employee_id"] for t in items} | {t["assignee_id"] for t in items if t.get("assignee_id")})
    return ToolOutcome(
        [
            {
                "ticket_id": t["id"],
                "title": t["title"],
                "category": t["category"],
                "priority": t["priority"],
                "status": t["status"],
                "raised_by": names.get(t["employee_id"]),
                "assignee": names.get(t["assignee_id"]) if t.get("assignee_id") else None,
            }
            for t in items
        ]
    )


async def _search_employees(ctx: ToolContext, args: SearchEmployeesArgs) -> ToolOutcome:
    data = await ctx.api.request("GET", "/employees", params={"q": args.query, "limit": 5})
    return ToolOutcome([{k: e.get(k) for k in ("id", "name", "email", "role")} for e in data.get("items", [])])


async def _list_projects(ctx: ToolContext, _: BaseModel) -> ToolOutcome:
    data = await ctx.api.request("GET", "/employees/projects/catalog")
    items = data.get("items", data) if isinstance(data, dict) else data
    return ToolOutcome([{k: p.get(k) for k in ("id", "name", "status")} for p in items or []])


# ---- write tools


async def _apply_leave(ctx: ToolContext, args: ApplyLeaveArgs) -> ToolOutcome:
    payload = args.model_dump(mode="json")
    data = await ctx.api.request("POST", "/leaves/requests", json=payload)
    span = args.start_date.isoformat() if args.start_date == args.end_date else f"{args.start_date.isoformat()} to {args.end_date.isoformat()}"
    half = f" ({args.half_day_period.replace('_', ' ').lower()})" if args.is_half_day and args.half_day_period else ""
    status = data.get("status", "PENDING")
    summary = (
        f"Your {args.leave_type.lower()} leave request for {span}{half} has been submitted. "
        + ("It was auto-approved." if status == "APPROVED" else "Status: pending approval.")
    )
    return ToolOutcome(data, summary, (f"leave_request:{data.get('id')}",))


async def _load_leave_for_decision(ctx: ToolContext, request_id: int) -> LeaveRequest | None:
    leave = (await ctx.db.execute(select(LeaveRequest).where(LeaveRequest.id == request_id))).scalar_one_or_none()
    await ctx.db.commit()  # see _employee_names
    return leave


async def _check_leave_scope(ctx: ToolContext, args: LeaveDecisionArgs) -> LeaveRequest:
    leave = await _load_leave_for_decision(ctx, args.request_id)
    # Same refusal whether the request is missing or out of scope: never leak existence.
    if leave is None or not ctx.user.can_act_on_employee(Capability.DECIDE_LEAVE, leave.employee_id):
        raise PermissionDenied(Capability.DECIDE_LEAVE, "You can only approve or reject leave requests from your team.")
    if leave.employee_id == ctx.user.id:
        raise PermissionDenied(Capability.DECIDE_LEAVE, "You can't approve or reject your own leave request.")
    return leave


async def _describe_leave_decision(ctx: ToolContext, args: LeaveDecisionArgs, verb: str) -> str:
    leave = await _check_leave_scope(ctx, args)
    name = (await _employee_names(ctx.db, {leave.employee_id})).get(leave.employee_id, "an employee")
    span = leave.start_date.isoformat() if leave.start_date == leave.end_date else f"{leave.start_date} to {leave.end_date}"
    return f"{verb} the pending {leave.leave_type.value.lower()} leave request from {name} for {span} (request #{leave.id})?"


async def _decide_leave(ctx: ToolContext, args: LeaveDecisionArgs, action: str) -> ToolOutcome:
    leave = await _check_leave_scope(ctx, args)
    name = (await _employee_names(ctx.db, {leave.employee_id})).get(leave.employee_id, "the employee")
    data = await ctx.api.request("POST", f"/leaves/requests/{args.request_id}/{action}", json={})
    past = "approved" if action == "approve" else "rejected"
    return ToolOutcome(data, f"Leave request #{args.request_id} from {name} has been {past}.", (f"leave_request:{args.request_id}",))


async def _create_ticket(ctx: ToolContext, args: CreateTicketArgs) -> ToolOutcome:
    data = await ctx.api.request("POST", "/tickets", json=args.model_dump())
    summary = f"Ticket #{data.get('id')} \"{args.title}\" has been created ({args.priority.lower()} priority, {args.category}). Status: {data.get('status', 'OPEN')}."
    return ToolOutcome(data, summary, (f"ticket:{data.get('id')}",))


async def _assign_ticket(ctx: ToolContext, args: AssignTicketArgs) -> ToolOutcome:
    data = await ctx.api.request("POST", f"/tickets/{args.ticket_id}/assign", json={"assignee_id": args.assignee_id})
    name = (await _employee_names(ctx.db, {args.assignee_id})).get(args.assignee_id, f"employee #{args.assignee_id}")
    return ToolOutcome(data, f"Ticket #{args.ticket_id} has been assigned to {name}.", (f"ticket:{args.ticket_id}",))


async def _describe_assign_ticket(ctx: ToolContext, args: AssignTicketArgs) -> str:
    name = (await _employee_names(ctx.db, {args.assignee_id})).get(args.assignee_id, f"employee #{args.assignee_id}")
    return f"Assign ticket #{args.ticket_id} to {name}?"


async def _update_ticket_status(ctx: ToolContext, args: TicketStatusArgs) -> ToolOutcome:
    data = await ctx.api.request("POST", f"/tickets/{args.ticket_id}/status", json={"status": args.status})
    return ToolOutcome(data, f"Ticket #{args.ticket_id} is now {args.status.replace('_', ' ').lower()}.", (f"ticket:{args.ticket_id}",))


async def _create_announcement(ctx: ToolContext, args: AnnouncementArgs) -> ToolOutcome:
    data = await ctx.api.request("POST", "/announcements", json=args.model_dump())
    return ToolOutcome(data, f"Announcement \"{args.title}\" has been published.", (f"announcement:{data.get('id')}",))


async def _assign_project(ctx: ToolContext, args: AssignProjectArgs) -> ToolOutcome:
    data = await ctx.api.request(
        "POST", f"/employees/{args.employee_id}/projects", json={"project_id": args.project_id, "role_on_project": args.role_on_project}
    )
    name = (await _employee_names(ctx.db, {args.employee_id})).get(args.employee_id, f"employee #{args.employee_id}")
    project = await _project_name(ctx, args.project_id)
    role = f" as {args.role_on_project}" if args.role_on_project else ""
    return ToolOutcome(data, f"{name} has been assigned to {project}{role}.", (f"employee:{args.employee_id}", f"project:{args.project_id}"))


async def _project_name(ctx: ToolContext, project_id: int) -> str:
    projects = (await _list_projects(ctx, NoArgs())).data
    return next((p["name"] for p in projects if p["id"] == project_id), f"project #{project_id}")


async def _describe_assign_project(ctx: ToolContext, args: AssignProjectArgs) -> str:
    name = (await _employee_names(ctx.db, {args.employee_id})).get(args.employee_id, f"employee #{args.employee_id}")
    project = await _project_name(ctx, args.project_id)
    role = f" as {args.role_on_project}" if args.role_on_project else ""
    return f"Assign {name} to {project}{role}?"


async def _create_project(ctx: ToolContext, args: CreateProjectArgs) -> ToolOutcome:
    data = await ctx.api.request("POST", "/employees/projects/catalog", json=args.model_dump())
    return ToolOutcome(data, f"Project \"{data.get('name', args.name)}\" has been created ({args.status.lower()}).", (f"project:{data.get('id')}",))


async def _plain(text: str) -> str:
    return text


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        # --- reads
        Tool("get_my_leave_balance", "Get the current user's remaining leave balance per leave type.",
             _props({}, []), NoArgs, Capability.OWN_LEAVE_BALANCE, _get_my_leave_balance),
        Tool("get_my_leave_requests", "List the current user's own leave requests and their status.",
             _props({}, []), NoArgs, Capability.OWN_LEAVE_BALANCE, _get_my_leave_requests),
        Tool("get_my_tickets", "List tickets raised by or assigned to the current user, with their status.",
             _props({}, []), NoArgs, Capability.CREATE_TICKET, _get_my_tickets),
        Tool("list_pending_leave_requests",
             "List pending leave requests the current user may approve or reject (manager/admin). "
             "Use it to find the request_id for an employee's pending leave.",
             _props({}, []), NoArgs, Capability.DECIDE_LEAVE, _list_pending_leave_requests),
        Tool("list_open_tickets", "List open and in-progress tickets with ids, to find a ticket_id (manager/admin).",
             _props({}, []), NoArgs, Capability.MANAGE_TICKET, _list_open_tickets),
        Tool("search_employees", "Find employees by name or email to get their employee id.",
             _props({"query": {**_STR, "description": "Name or email to search for"}}, ["query"]),
             SearchEmployeesArgs, Capability.SKILL_SEARCH, _search_employees),
        Tool("list_projects", "List all projects with their ids (manager/admin).",
             _props({}, []), NoArgs, Capability.ASSIGN_PROJECT, _list_projects),
        # --- writes
        Tool("apply_leave", "Apply for leave for the current user.",
             _props({
                 "leave_type": {**_STR, "enum": ["CASUAL", "SICK", "EARNED"]},
                 "start_date": {**_STR, "description": "YYYY-MM-DD"},
                 "end_date": {**_STR, "description": "YYYY-MM-DD (same as start_date for one day)"},
                 "reason": {**_STR, "description": "Short reason, at least 3 characters"},
                 "is_half_day": {"type": "boolean"},
                 "half_day_period": {**_STR, "enum": ["FIRST_HALF", "SECOND_HALF"]},
             }, ["leave_type", "start_date", "end_date", "reason"]),
             ApplyLeaveArgs, Capability.CREATE_OWN_LEAVE, _apply_leave, mutates=True),
        Tool("approve_leave", "Approve a pending leave request by its request_id.",
             _props({"request_id": _INT}, ["request_id"]), LeaveDecisionArgs, Capability.DECIDE_LEAVE,
             lambda ctx, a: _decide_leave(ctx, a, "approve"), mutates=True, requires_confirmation=True,
             describe=lambda ctx, a: _describe_leave_decision(ctx, a, "Approve")),
        Tool("reject_leave", "Reject a pending leave request by its request_id.",
             _props({"request_id": _INT}, ["request_id"]), LeaveDecisionArgs, Capability.DECIDE_LEAVE,
             lambda ctx, a: _decide_leave(ctx, a, "reject"), mutates=True, requires_confirmation=True,
             describe=lambda ctx, a: _describe_leave_decision(ctx, a, "Reject")),
        Tool("create_ticket", "Create a support ticket for the current user.",
             _props({
                 "title": {**_STR, "description": "Short title"},
                 "description": {**_STR, "description": "What the problem is, at least 5 characters"},
                 "category": {**_STR, "enum": ["IT", "HR", "ONBOARDING"]},
                 "priority": {**_STR, "enum": ["LOW", "MEDIUM", "HIGH"]},
             }, ["title", "description", "category", "priority"]),
             CreateTicketArgs, Capability.CREATE_TICKET, _create_ticket, mutates=True),
        Tool("assign_ticket", "Assign a ticket to an employee (manager/admin).",
             _props({"ticket_id": _INT, "assignee_id": _INT}, ["ticket_id", "assignee_id"]), AssignTicketArgs,
             Capability.MANAGE_TICKET, _assign_ticket, mutates=True, requires_confirmation=True, describe=_describe_assign_ticket),
        Tool("update_ticket_status", "Change a ticket's status (manager/admin).",
             _props({"ticket_id": _INT, "status": {**_STR, "enum": ["OPEN", "IN_PROGRESS", "RESOLVED"]}}, ["ticket_id", "status"]),
             TicketStatusArgs, Capability.MANAGE_TICKET, _update_ticket_status, mutates=True, requires_confirmation=True,
             describe=lambda ctx, a: _plain(f"Change ticket #{a.ticket_id} to {a.status.replace('_', ' ').lower()}?")),
        Tool("create_announcement", "Publish a company announcement (manager/admin).",
             _props({"title": _STR, "body": {**_STR, "description": "Announcement text, at least 5 characters"}}, ["title", "body"]),
             AnnouncementArgs, Capability.CREATE_ANNOUNCEMENT, _create_announcement, mutates=True, requires_confirmation=True,
             describe=lambda ctx, a: _plain(f"Publish the announcement \"{a.title}\": {a.body}")),
        Tool("assign_employee_to_project", "Assign an employee to a project, optionally with a role (manager/admin).",
             _props({"employee_id": _INT, "project_id": _INT, "role_on_project": _STR}, ["employee_id", "project_id"]),
             AssignProjectArgs, Capability.ASSIGN_PROJECT, _assign_project, mutates=True, requires_confirmation=True,
             describe=_describe_assign_project),
        Tool("create_project", "Create a new project (manager/admin).",
             _props({"name": _STR, "description": _STR,
                     "status": {**_STR, "enum": ["ONGOING", "COMPLETED", "ON_HOLD", "PLANNED"]}}, ["name"]),
             CreateProjectArgs, Capability.ASSIGN_PROJECT, _create_project, mutates=True, requires_confirmation=True,
             describe=lambda ctx, a: _plain(f"Create the project \"{a.name}\" ({a.status.lower()})?")),
    ]
}  # fmt: skip


def validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first.get("loc", []))
    return f"{field}: {first.get('msg')}" if field else str(first.get("msg"))
