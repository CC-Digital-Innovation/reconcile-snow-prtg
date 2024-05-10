from dataclasses import dataclass


@dataclass(slots=True)
class Country:
    id: str
    name: str


@dataclass(slots=True)
class Location:
    id: str
    name: str
    country: Country | None
    street: str
    city: str
    state: str
