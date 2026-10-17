# AI Permissions Matrix

Source of truth: `backend/app/services/ai/permissions.py` (`PERMISSION_MATRIX`). Every AI
component reads the same matrix. The existing backend APIs still enforce their own role checks,
so the AI layer is an extra, earlier gate and never the only one.

**Legend**
- **Full:** allowed.
- **Scoped:** allowed only for the user's own records or, for managers, their direct reports.
- **No:** refused.

| AI capability | Employee | Manager | Admin |
|---|:---:|:---:|:---:|
| Ask HR policy questions | Full | Full | Full |
| Re-index HR policies | No | No | Full |
| Own leave balance | Full | Full | Full |
| Another employee's leave balance | No | Scoped (team) | Full |
| Own project assignments | Full | Full | Full |
| All project assignments | No | Scoped (team) | Full |
| Search employees by skill | Scoped (directory fields only) | Full | Full |
| Generate SQL over HR data | Scoped | Scoped | Full |
| View raw SQL | No | Full | Full |
| Create own leave request | Full | Full | Full |
| Approve / reject leave | No | Scoped (team) | Full |
| Create ticket | Full | Full | Full |
| Assign / update ticket | No | Full | Full |
| Create announcement | No | Full | Full |
| Assign employee to project | No | Full | Full |
| Payroll data | Own only (existing `/finance/*/me` APIs) | Own only | Full |
| Passwords, bank, PAN, date of birth | No | No | No |

**Manager team scope.** A manager's team is the set of employees whose `manager_id` is the
manager. The existing `POST /leaves/requests/{id}/approve` route lets any manager approve any
pending request. The AI layer is stricter and only acts on the manager's team.

**Forbidden columns.** These never reach the LLM or the user, whatever the role:
`hashed_password`, `bank_name`, `bank_account_number`, `bank_account_name`, `bank_branch`,
`bank_ifsc`, `pan_number`, `pan_name`, `pan_dob`, `date_of_birth`, `current_salary_usd`,
`profile_photo_path`, `profile_photo_mime`. Payroll records are never queryable through SQL.

**Refusals never leak existence.** Messages such as *"You do not have permission to view another
employee's payroll information."* are returned before any lookup, so a refusal never reveals
whether a record exists.
