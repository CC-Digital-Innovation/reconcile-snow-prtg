from typing import Union

from dataclasses import dataclass

@dataclass
class Country:
    id: str
    name: str

@dataclass
class Location:
    id: str
    name: str
    country: Union[Country, None]
    street: str
    city: str
    state: str
