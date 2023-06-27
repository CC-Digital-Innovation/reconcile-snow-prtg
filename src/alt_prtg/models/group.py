from dataclasses import dataclass
from typing import List

@dataclass
class Group:
    id: int
    name: str

    location: str
    service_url: str
    tags: List[str]
    priority: int
    is_active: bool
    is_paused: bool
