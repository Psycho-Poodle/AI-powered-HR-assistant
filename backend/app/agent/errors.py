"""Provider failures expose stable codes, never SDK exceptions or credentials."""


class LLMFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
