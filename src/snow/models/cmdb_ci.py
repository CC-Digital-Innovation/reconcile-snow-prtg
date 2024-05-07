from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Union

from pydantic import BaseModel


@dataclass
class Manufacturer:
    id: str
    name: str

@dataclass
class ConfigItem:
    id: str
    name: str
    ip_address: Union[IPv4Address, None]
    manufacturer: Union[Manufacturer, None]
    model_number: str
    stage: str
    category: str
    sys_class: str
    link: str
    prtg_id: Union[int, None]
    is_internal: bool

class CIBody(BaseModel):
    """Model for API endpoint body to sync a configuration item from 
    ServiceNow."""
    # PRTG
    prtg_url: str
    prtg_api_key: str

    ci: ConfigItem
