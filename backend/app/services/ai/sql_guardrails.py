"""Validation of LLM-generated SQL before it is executed.

This is one of several layers. Even if a query passes here, it runs on a read-only
connection with role-scoped views and a SQLite authorizer (see ``sql_agent.py``).
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.tokens import TokenType

from app.services.ai.permissions import FORBIDDEN_COLUMNS

BLOCKED_KEYWORDS = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE", "TRUNCATE",
        "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX", "ANALYZE", "UPSERT", "GRANT", "REVOKE",
    }
)  # fmt: skip

BLOCKED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zipfile"})

_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Merge,
    exp.TruncateTable,
)


class SQLValidationError(Exception):
    """``reason`` is safe to show the LLM on retry; it is never shown to end users."""

    def __init__(self, code: str, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True)
class ValidatedSQL:
    # Row-limited query that is actually executed.
    sql: str
    # The model's query, normalized and pretty-printed, for display.
    display_sql: str
    tables: tuple[str, ...]


def _strip_trailing_semicolons(sql: str) -> str:
    sql = sql.strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


def validate_select(sql: str, allowed_tables: frozenset[str], max_rows: int) -> ValidatedSQL:
    """Return a safe, row-limited version of ``sql`` or raise ``SQLValidationError``."""
    sql = _strip_trailing_semicolons(sql or "")
    if not sql:
        raise SQLValidationError("EMPTY", "No SQL was produced.")

    # Keyword scan on real tokens, so words inside string literals ('update my address') are fine.
    try:
        tokens = sqlglot.tokenize(sql, read="sqlite")
    except Exception as exc:  # noqa: BLE001
        raise SQLValidationError("PARSE_ERROR", "The SQL could not be tokenized.") from exc
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            raise SQLValidationError("MULTIPLE_STATEMENTS", "Only one SQL statement is allowed.")
        if token.token_type not in (TokenType.STRING, TokenType.IDENTIFIER) and token.text.upper() in BLOCKED_KEYWORDS:
            raise SQLValidationError("FORBIDDEN_KEYWORD", f"The keyword {token.text.upper()} is not allowed.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        raise SQLValidationError("PARSE_ERROR", f"The SQL is not valid SQLite: {str(exc)[:200]}") from exc
    if len(statements) != 1:
        raise SQLValidationError("MULTIPLE_STATEMENTS", "Only one SQL statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLValidationError("NOT_SELECT", "Only SELECT queries are allowed.")
    if any(isinstance(node, _WRITE_NODES) for node in tree.walk()):
        raise SQLValidationError("NOT_SELECT", "Only SELECT queries are allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLValidationError("QUALIFIED_TABLE", f"Use the table name {name} without a schema prefix.")
        if name in cte_names:
            continue
        if name not in allowed_tables:
            raise SQLValidationError("TABLE_NOT_ALLOWED", f"The table {name} is not available.")
        tables.add(name)

    for column in tree.find_all(exp.Column):
        if column.name.lower() in FORBIDDEN_COLUMNS:
            raise SQLValidationError("FORBIDDEN_COLUMN", f"The column {column.name} is not available.")

    for func in tree.find_all(exp.Anonymous, exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name in BLOCKED_FUNCTIONS:
            raise SQLValidationError("FORBIDDEN_FUNCTION", f"The function {name} is not allowed.")

    # Enforce the row cap without rewriting the user's query: wrap it. One extra row tells us
    # whether the result was truncated.
    limited = f"SELECT * FROM (\n{tree.sql(dialect='sqlite')}\n) LIMIT {max_rows + 1}"
    return ValidatedSQL(sql=limited, display_sql=tree.sql(dialect="sqlite", pretty=True), tables=tuple(sorted(tables)))
