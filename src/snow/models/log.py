from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    SUCCESS = 'success'
    FAILED = 'failed'


@dataclass(slots=True)
class Log:
    request_id: str
    state: State
    response_msg: str
