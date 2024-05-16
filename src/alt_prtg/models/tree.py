from anytree import NodeMixin
from anytree.node import util

from . import Device, Group


class Node(NodeMixin):
    """Represents a PRTG tree structure of a company/location."""
    def __init__(self, prtg_obj: Device | Group, parent: NodeMixin | None = None):
        self.prtg_obj = prtg_obj
        self.parent = parent

    # copied from anytree.Node and revised to get PRTG object's name
    def __repr__(self):
        args = ["%r" % self.separator.join([""] + [node.prtg_obj.name for node in self.path])]
        return util._repr(self, args=args, nameblacklist=["prtg_obj"])
