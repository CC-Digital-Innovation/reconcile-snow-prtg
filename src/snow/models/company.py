from dataclasses import dataclass


@dataclass(slots=True)
class Company:
    id: str
    name: str
    abbreviated_name: str
    prtg_device_name_format: str | None
