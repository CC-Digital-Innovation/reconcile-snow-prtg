from dataclasses import dataclass


@dataclass
class Company:
    id: str
    name: str
    abbreviated_name: str
    prtg_device_name_format: str
