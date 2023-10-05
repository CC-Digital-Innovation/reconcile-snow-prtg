from typing import Union

from anytree import NodeMixin
from anytree.node import util

from . import Device, Group


class Node(NodeMixin):
    """Represents an immutable PRTG tree structure of a company/location."""
    def __init__(self, prtg_obj: Union[Device, Group], parent: Union[NodeMixin, None] = None):
        self.prtg_obj = prtg_obj
        self.parent = parent

    def __eq__(self, other):
        if other.__class__ is self.__class__:
            return (self.prtg_obj, self.parent) == (other.prtg_obj, other.parent)

    # copied from anytree.Node and revised to get PRTG object's name
    def __repr__(self):
        args = ["%r" % self.separator.join([""] + [node.prtg_obj.name for node in self.path])]
        return util._repr(self, args=args, nameblacklist=["prtg_obj"])
