from dataclasses import dataclass
from typing import List, Union

from .common import Status

# Immutable class to have autogenerated __hash__() method in order 
# to take advantage of set operations
@dataclass(frozen=True)
class Group:
    id: Union[int, None]
    name: str
    priority: int
    tags: List[str]
    location: str
    status: Status
    is_active: bool

    # Allow subclass comparison for adapters
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return (self.id, self.name, self.priority, self.tags, self.location, self.status, self.is_active) == (other.id, other.name, other.priority, other.tags, other.location, other.status, other.is_active)
        return NotImplemented
