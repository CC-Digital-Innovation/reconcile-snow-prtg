from dataclasses import dataclass

from prtg import Icon

from .common import Status


@dataclass(slots=True)
class Device:
    id: int | None
    name: str
    host: str
    service_url: str
    priority: int
    tags: list[str]
    location: str
    icon: Icon | None
    status: Status
    is_active: bool
