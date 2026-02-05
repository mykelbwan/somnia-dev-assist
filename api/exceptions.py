class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.detail)


class EmptyInputError(APIError):
    def __init__(self):
        super().__init__(400, "EMPTY_INPUT")
