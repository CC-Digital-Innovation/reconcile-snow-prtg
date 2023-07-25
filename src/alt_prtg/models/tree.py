from dataclasses import dataclass
from typing import Union

from anytree import NodeMixin

from . import Device, Group, Probe

@dataclass
class Node(NodeMixin):
    """Represents a PRTG tree structure of a company/location."""
    prtg_obj: Union[Device, Group, Probe]
    parent: Union[NodeMixin, None] = None
    children: Union[NodeMixin, None] = None
