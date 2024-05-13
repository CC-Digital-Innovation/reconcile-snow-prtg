from dataclasses import dataclass

from .common import Status


@dataclass(slots=True)
class Group:
    id: int | None
    name: str
    priority: int
    tags: set[str]
    location: str
    status: Status
    is_active: bool

    def __eq__(self, other: object) -> bool:
        """Custom __eq__ with isinstance() to work with subclasses"""
        if isinstance(other, Group):
            return ((self.id, self.name, self.priority, self.tags, 
                     self.location, self.status, self.is_active) == 
                    (other.id, other.name, other.priority, other.tags, 
                     other.location, other.status, other.is_active))
        return NotImplemented
