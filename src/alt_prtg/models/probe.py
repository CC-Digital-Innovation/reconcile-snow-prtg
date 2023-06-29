from dataclasses import dataclass

from .common import Status

@dataclass
class Probe:
    id: int
    name: str
    parent_id: int
    priority: int
    location: str
    status: Status
