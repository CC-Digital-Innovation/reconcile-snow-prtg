from dataclasses import dataclass

from typing import Union


@dataclass
class Properties:
    name: str = None
    host: str = None
    location: str = None
