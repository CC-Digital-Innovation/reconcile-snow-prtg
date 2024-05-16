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
    tags: set[str]
    location: str
    icon: Icon | None
    status: Status
    is_active: bool

    def __eq__(self, other: object) -> bool:
        """Custom __eq__ with isinstance() to work with subclasses"""
        if isinstance(other, Device):
            return ((self.id, self.name, self.host, self.service_url,
                     self.priority, self.tags, self.location, self.icon,
                     self.status, self.is_active) ==
                     (other.id, other.name, other.host, other.service_url,
                      other.priority, other.tags, other.location, other.icon,
                      other.status, other.is_active))
        return NotImplemented
