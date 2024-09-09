from collections import defaultdict
from dataclasses import dataclass, fields
from functools import reduce, partial
from operator import getitem
from string import Formatter

from prtg import Icon

from .models import ConfigItem, Company, Location
from alt_prtg.models import Device, Group, Status, Node
from snow import SnowController


def _check_required_fields(ci: ConfigItem, name_format: str):
    for _, key_name, _, _ in Formatter().parse(name_format):
        if key_name is None:
            continue
        # reduce to get value of nested attributes
        value = reduce(getattr, key_name.split('.'), ci)
        # raise if value is missing
        if value is None or value == '':
            raise ValueError(f'Configuration item "{ci.name}" is missing required attribute "{key_name}".')


@dataclass(eq=False, slots=True)
class PrtgDeviceAdapter(Device):
    """Adapter for ServiceNow configuration items to PRTG devices. Recommended 
    to use the classmethod from_ci to instantiate this class."""
    ci: ConfigItem

    @classmethod
    def from_ci(cls, ci: ConfigItem, name_format: str | None = None):
        if name_format:
            # check for required attributes
            _check_required_fields(ci, name_format)
            # pass shallow copy of ci to work with dotted attribute format, e.g., manufacturer.name
            name = name_format.format_map({field.name: getattr(ci, field.name) for field in fields(ci)})
        else:
            # default to CI name
            name = ci.name

        if not ci.stage:
            raise ValueError(f'Configuration item "{ci.name}" is missing required attribute Used for.')
        if not ci.category:
            raise ValueError(f'Configuration item "{ci.name}" is missing required attribute Category.')
        tags = {ci.stage, ci.category}

        icon = None  # default to None
        try:
            icon = Icon[ci.manufacturer.name.upper()]
        except KeyError:
            # Multiple VMware names
            if ci.manufacturer.name == 'VMware, Inc.':
                icon = Icon.VMWARE
        except AttributeError:
            pass  # None or other type
        return cls(ci.prtg_id, name, str(ci.ip_address), ci.link, 3, tags, '', icon, Status.UP, True, ci)


class PrtgGroupAdapter(Group):
    """Adapter for ServiceNow configuration item details to represent a PRTG 
    group with common defaults."""
    def __init__(self, name: str):
        super(PrtgGroupAdapter, self).__init__(None, name, 3, set(), '', Status.UP, True)


def _build_pseudo_tree(depth: int):
    """Recursive function that dynamically builds psuedo tree depth with leaf nodes containing a list.
    
    E.g., build_tree(2) allows a defaultdict like:
        {
            group-1: {
                group-2: []
            }
        }
    """
    factory = partial(_build_pseudo_tree, depth - 1) if depth > 1 else list
    return defaultdict(factory)


# Tree creation is more complex so avoided a class object
def get_prtg_tree_adapter(company: Company,
                          location: Location,
                          config_items: list[ConfigItem],
                          controller: SnowController,
                          root_is_site = False,
                          min_device: int = 0) -> Node:
    # Default company's abbreviated name if it exists
    company_name = company.abbreviated_name if company.abbreviated_name else company.name
    # Group format for all groups. Some tools like logging requires a particular format for groups in PRTG.
    group_name_fmt = f'[{company_name}] ' + '{}'

    if not root_is_site:
        # Initialize root node
        root_group = PrtgGroupAdapter(f'[{company_name}]')
        root = Node(root_group)

        # Initialize site node
        site_group = PrtgGroupAdapter(group_name_fmt.format(location.name))
        site = Node(site_group, root)
    else:
        # Root is site so do not create separate groups
        root_group = PrtgGroupAdapter(group_name_fmt.format(location.name))
        root = site = Node(root_group)

    # Required number of devices before organizing devices into groups
    num_devices = controller.get_device_count(company, location)
    if num_devices < min_device:
        # Not enough devices. Ignore structure and simply create devices in site group.
        for ci in config_items:
            ci_adapter = PrtgDeviceAdapter.from_ci(ci, company.prtg_device_name_format)
            Node(ci_adapter, parent=site)
        return root

    # Enough devices to organize into groups

    # Tuple of attributes used for grouping
    # Order matters: left to right represents going deeper into the tree
    filters = ('is_internal', 'stage', 'category')

    # build temporary tree
    pseudo_tree = _build_pseudo_tree(len(filters))

    # Add ci to psuedo tree as leaf node
    for ci in config_items:
        # Grab group names
        filter_values = [getattr(ci, attr) for attr in filters]
        reduce(getitem, filter_values[:-1], pseudo_tree)[filter_values[-1]].append(ci)

    # Build actually tree from pseudo tree
    # First group is based on bool attribute is_internal
    if True in pseudo_tree:
        # Internal devices
        internal_node = Node(PrtgGroupAdapter(group_name_fmt.format('CC Infrastructure')), parent=site)
        # No more groups required for internal devices, simply add devices
        for _, categories in pseudo_tree[True].items():
            for _, cis in categories.items():
                for ci in cis:
                    Node(PrtgDeviceAdapter.from_ci(ci, company.prtg_device_name_format), parent=internal_node)
    if False in pseudo_tree:
        # Customer managed devices
        external_node = Node(PrtgGroupAdapter(group_name_fmt.format('Customer Managed Infrastructure')), parent=site)
        for stage, categories in pseudo_tree[False].items():
            stage_node = Node(PrtgGroupAdapter(group_name_fmt.format(stage)), parent=external_node)
            for category, cis in categories.items():
                cat_node = Node(PrtgGroupAdapter(group_name_fmt.format(category)), parent=stage_node)
                # specific case for Access Points
                if category == 'Network':
                    ap_node = Node(PrtgGroupAdapter(group_name_fmt.format('APs')), parent=cat_node)
                    for ci in cis:
                        if ci.sys_class == 'Wireless Access Point':
                            Node(PrtgDeviceAdapter.from_ci(ci, company.prtg_device_name_format), parent=ap_node)
                        else:
                            Node(PrtgDeviceAdapter.from_ci(ci, company.prtg_device_name_format), parent=cat_node)
                    if not ap_node.children:
                        # no children means group is not necessary, remove from tree
                        ap_node.parent = None
                    continue
                for ci in cis:
                    Node(PrtgDeviceAdapter.from_ci(ci, company.prtg_device_name_format), parent=cat_node)
    return root
