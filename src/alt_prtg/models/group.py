from dataclasses import dataclass, field

from .common import Status


@dataclass(slots=True)
class Group:
    id: int | None = field(compare=False)
    name: str
    priority: int = field(compare=False)
    tags: list[str] = field(compare=False)
    location: str = field(compare=False)
    status: Status = field(compare=False)
    is_active: bool = field(compare=False)
