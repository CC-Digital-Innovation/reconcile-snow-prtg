from ipaddress import IPv4Address
from pydantic import BaseModel
from typing import Union

class SnowData(BaseModel):
    # PRTG KEYS
    prtg_url: str
    prtg_api_key: str

    #PRTG Inputs
    objid: Union[int,str]
    hostname: str = None
    ip: Union[IPv4Address, None]
    manufactuer_model : str = None
    manufacturer_number: str = None
    location: str = None

    # Parent Group from SNOW
    category: str = None

    # Grandparent Group from SNOW
    used_for: str = None

    min_devices: int = None