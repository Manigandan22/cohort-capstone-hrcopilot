"""Single source of truth for what each role may do through the AI layer.

The router, the SQL agent's data scoping and the action agent's tool list all read from
``PERMISSION_MATRIX`` so that the AI layer can never grant more than the matrix documented
in ``docs/ai_permissions_matrix.md``. The existing backend APIs still enforce their own role
checks; this layer is an additional, earlier gate, not a replacement.
"""

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.enums import Role


class Capability(str, Enum):
    POLICY_QA = "POLICY_QA"
    REINDEX_POLICIES = "REINDEX_POLICIES"
    OWN_LEAVE_BALANCE = "OWN_LEAVE_BALANCE"
    OTHERS_LEAVE_BALANCE = "OTHERS_LEAVE_BALANCE"
    OWN_PROJECTS = "OWN_PROJECTS"
    ALL_PROJECT_ASSIGNMENTS = "ALL_PROJECT_ASSIGNMENTS"
    SKILL_SEARCH = "SKILL_SEARCH"
    SQL_QUERY = "SQL_QUERY"
    VIEW_RAW_SQL = "VIEW_RAW_SQL"
    CREATE_OWN_LEAVE = "CREATE_OWN_LEAVE"
    DECIDE_LEAVE = "DECIDE_LEAVE"
    CREATE_TICKET = "CREATE_TICKET"
    MANAGE_TICKET = "MANAGE_TICKET"
    CREATE_ANNOUNCEMENT = "CREATE_ANNOUNCEMENT"
    ASSIGN_PROJECT = "ASSIGN_PROJECT"
    PAYROLL = "PAYROLL"
    SENSITIVE_PERSONAL = "SENSITIVE_PERSONAL"


class Access(str, Enum):
    FULL = "FULL"
    # Allowed, but restricted to the user's own records or their team (see docs).
    SCOPED = "SCOPED"
    NONE = "NONE"


_F, _S, _N = Access.FULL, Access.SCOPED, Access.NONE

# Columns: EMPLOYEE, MANAGER, ADMIN
PERMISSION_MATRIX: dict[Capability, dict[Role, Access]] = {
    Capability.POLICY_QA: {Role.EMPLOYEE: _F, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.REINDEX_POLICIES: {Role.EMPLOYEE: _N, Role.MANAGER: _N, Role.ADMIN: _F},
    Capability.OWN_LEAVE_BALANCE: {Role.EMPLOYEE: _F, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.OTHERS_LEAVE_BALANCE: {Role.EMPLOYEE: _N, Role.MANAGER: _S, Role.ADMIN: _F},
    Capability.OWN_PROJECTS: {Role.EMPLOYEE: _F, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.ALL_PROJECT_ASSIGNMENTS: {Role.EMPLOYEE: _N, Role.MANAGER: _S, Role.ADMIN: _F},
    Capability.SKILL_SEARCH: {Role.EMPLOYEE: _S, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.SQL_QUERY: {Role.EMPLOYEE: _S, Role.MANAGER: _S, Role.ADMIN: _F},
    Capability.VIEW_RAW_SQL: {Role.EMPLOYEE: _N, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.CREATE_OWN_LEAVE: {Role.EMPLOYEE: _F, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.DECIDE_LEAVE: {Role.EMPLOYEE: _N, Role.MANAGER: _S, Role.ADMIN: _F},
    Capability.CREATE_TICKET: {Role.EMPLOYEE: _F, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.MANAGE_TICKET: {Role.EMPLOYEE: _N, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.CREATE_ANNOUNCEMENT: {Role.EMPLOYEE: _N, Role.MANAGER: _F, Role.ADMIN: _F},
    Capability.ASSIGN_PROJECT: {Role.EMPLOYEE: _N, Role.MANAGER: _F, Role.ADMIN: _F},
    # Payroll is never exposed through SQL. Own payroll only via the existing /finance/*/me APIs.
    Capability.PAYROLL: {Role.EMPLOYEE: _S, Role.MANAGER: _S, Role.ADMIN: _F},
    # Passwords, bank details, PAN, date of birth: never available to anyone through AI.
    Capability.SENSITIVE_PERSONAL: {Role.EMPLOYEE: _N, Role.MANAGER: _N, Role.ADMIN: _N},
}

# User-facing refusals. They never confirm or deny that a record exists.
REFUSALS: dict[Capability, str] = {
    Capability.REINDEX_POLICIES: "You do not have permission to manage the HR policy index.",
    Capability.OTHERS_LEAVE_BALANCE: "You do not have permission to view another employee's leave information.",
    Capability.ALL_PROJECT_ASSIGNMENTS: "You do not have permission to view all project assignments.",
    Capability.SQL_QUERY: "You do not have permission to run that data query.",
    Capability.DECIDE_LEAVE: "You do not have permission to approve or reject leave requests.",
    Capability.MANAGE_TICKET: "You do not have permission to assign or update tickets.",
    Capability.CREATE_ANNOUNCEMENT: "You do not have permission to create announcements.",
    Capability.ASSIGN_PROJECT: "You do not have permission to assign employees to projects.",
    Capability.PAYROLL: "You do not have permission to view another employee's payroll information.",
    Capability.SENSITIVE_PERSONAL: "I can't share passwords, bank details, PAN details or dates of birth.",
}

# Columns that must never reach the LLM or the user, whatever the role.
FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "hashed_password",
        "bank_name",
        "bank_account_number",
        "bank_account_name",
        "bank_branch",
        "bank_ifsc",
        "pan_number",
        "pan_name",
        "pan_dob",
        "date_of_birth",
        "current_salary_usd",
        "profile_photo_path",
        "profile_photo_mime",
    }
)


class PermissionDenied(Exception):
    def __init__(self, capability: Capability, message: str | None = None):
        self.capability = capability
        self.message = message or REFUSALS.get(capability, "You do not have permission to do that.")
        super().__init__(self.message)


@dataclass(frozen=True)
class UserContext:
    """Who is asking. Built from the authenticated user on every AI request."""

    id: int
    name: str
    role: Role
    department_id: int | None
    manager_id: int | None
    # Direct reports. Managers' "team" scope is limited to these employees.
    team_ids: frozenset[int] = field(default_factory=frozenset)

    def access(self, capability: Capability) -> Access:
        return PERMISSION_MATRIX[capability][self.role]

    def can(self, capability: Capability) -> bool:
        return self.access(capability) is not Access.NONE

    def require(self, capability: Capability) -> Access:
        level = self.access(capability)
        if level is Access.NONE:
            raise PermissionDenied(capability)
        return level

    def can_act_on_employee(self, capability: Capability, employee_id: int) -> bool:
        """Whether the user may touch another employee's records for ``capability``."""
        level = self.access(capability)
        if level is Access.FULL:
            return True
        if level is Access.SCOPED:
            return employee_id == self.id or employee_id in self.team_ids
        return False


async def load_user_context(db: AsyncSession, user: Employee) -> UserContext:
    team_ids: frozenset[int] = frozenset()
    if user.role in {Role.MANAGER, Role.ADMIN}:
        rows = await db.execute(select(Employee.id).where(Employee.manager_id == user.id))
        team_ids = frozenset(rows.scalars().all())
    return UserContext(
        id=user.id,
        name=user.name,
        role=user.role,
        department_id=user.department_id,
        manager_id=user.manager_id,
        team_ids=team_ids,
    )
