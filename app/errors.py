from fastapi import HTTPException


class GatewayError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, request_id: str | None = None, extra: dict | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.request_id = request_id
        self.extra = extra or {}
