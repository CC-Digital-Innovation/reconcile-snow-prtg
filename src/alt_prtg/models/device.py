from dataclasses import dataclass
from typing import List

from prtg import Icon

from .common import Status

@dataclass
class Device:
    id: int
    name: str
    host: str
    service_url: str
    parent_id: int
    priority: int
    tags: List[str]
    location: str
    icon: Icon
    status: Status
    is_active: bool
