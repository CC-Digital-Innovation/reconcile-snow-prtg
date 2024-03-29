from dataclasses import dataclass
from typing import List, Union

from .common import Status


@dataclass
class Group:
    id: Union[int, None]
    name: str
    priority: int
    tags: List[str]
    location: str
    status: Status
    is_active: bool

    # Allow comparison for adapters
    # Only compares name because SNOW does not store group objects
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return (self.name) == (other.name)
        return NotImplemented
