from dataclasses import dataclass
from ipaddress import IPv4Address

from pydantic import BaseModel


@dataclass(slots=True)
class Manufacturer:
    id: str
    name: str


@dataclass(slots=True)
class ConfigItem:
    """Dataclass for ServiceNow configuration items."""
    id: str
    name: str
    ip_address: IPv4Address | None
    manufacturer: Manufacturer | None
    model_number: str
    stage: str
    category: str
    sys_class: str
    link: str
    prtg_id: int |None
    is_internal: bool
    host_name: str | None = None


class CIBody(BaseModel):
    """Model for API endpoint body to sync a configuration item from ServiceNow."""
    prtg_url: str
    prtg_api_key: str
    company_name: str
    location_name: str
    ci: ConfigItem
