from dataclasses import dataclass
from ipaddress import IPv4Address


@dataclass(slots=True)
class Manufacturer:
    id: str
    name: str


@dataclass(slots=True)
class ConfigItem:
    id: str
    name: str
    ip_address: IPv4Address | None
    manufacturer: Manufacturer | None
    model_number: str
    stage: str
    category: str
    sys_class: str
    link: str
    prtg_id: int | None
    is_internal: bool
    host_name: str | None = None
