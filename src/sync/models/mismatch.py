from dataclasses import dataclass
from typing import List

from alt_prtg.models import Device
from snow.models import ConfigItem

@dataclass
class Field:
    """Object contains a mismatched field"""
    name: str
    expected: str
    current: str

@dataclass
class Detail:
    """Object contains two similar devices with a list of mismatched fields"""
    config_item: ConfigItem
    device: Device
    fields: List[Field]

@dataclass
class Mismatch:
    """Object contains mismatch records of comparing two lists of devices
    
    Attributes:
        snow (List[ConfigItem]): list of configuration items not in PRTG
        prtg (List[Device]): list of devices not in SNOW
        fields (List[Detail]): list of devices in both but with mismatched fields
    """
    snow: List[ConfigItem]
    prtg: List[Device]
    fields: List[Detail]
