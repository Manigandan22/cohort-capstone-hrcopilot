class AIRequestError(Exception):
    """An expected, user-facing failure of an AI request (refusal, blocked query, ...).

    ``message`` is shown to the user, so it must never contain internal details.
    """

    def __init__(self, status_code: int, code: str, message: str, audit_status: str = "ERROR"):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.audit_status = audit_status
        super().__init__(message)
