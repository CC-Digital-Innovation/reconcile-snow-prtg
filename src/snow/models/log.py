from dataclasses import dataclass


@dataclass(slots=True)
class Log:
    request_id: str
    state: str
    response_msg: str
