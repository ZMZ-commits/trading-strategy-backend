from pydantic import BaseModel


class RunRequest(BaseModel):
    config: dict = {}
