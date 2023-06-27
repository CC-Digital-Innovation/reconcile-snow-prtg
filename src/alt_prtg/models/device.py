from dataclasses import dataclass
from typing import Union

from prtg import Icon

from .common import Status
from .group import Group
from .probe import Probe

@dataclass
class Device:
    id: int
    name: str
    status: Status
    probe: Probe
    group: Group
    host: str
    priority: int
    location: str
    icon: Icon
    is_active: bool
    is_paused: bool
