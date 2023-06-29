from dataclasses import dataclass
from typing import List

from .common import Status

@dataclass
class Group:
    id: int
    name: str
    parent_id: int
    service_url: str
    priority: int
    tags: List[str]
    location: str
    status: Status
    is_active: bool
