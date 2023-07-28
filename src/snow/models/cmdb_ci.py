from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Union


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
    link: str
    prtg_id: Union[int, None]
    is_internal: bool
