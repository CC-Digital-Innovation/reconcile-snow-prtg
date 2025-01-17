from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, fields
from functools import reduce
from string import Formatter

from loguru import logger
from prtg import Icon

from alt_prtg.models import Device, Group, Node, Status
from snow import SnowController
from snow.models import Company, ConfigItem, Location

# map SNOW choice list names to formats
FORMAT_MAP = {
    'ip only': '{manufacturer.name} {model_number} ({ip_address})',
    'hostname + ip': '{manufacturer.name} {model_number} {host_name} ({ip_address})',
    'label + ip': '{manufacturer.name} {model_number} {label} ({ip_address})'
}

def _check_required_fields(ci: ConfigItem, name_format: str):
    # collect missing fields
    missing_fields = []
    for _, key_name, _, _ in Formatter().parse(name_format):
        if key_name is None:
            continue
        # reduce to get value of nested attributes
        value = reduce(getattr, key_name.split('.'), ci)
        if value is None or value == '':
            missing_fields.append(key_name)
    return missing_fields

@dataclass(eq=False, slots=True)
class PrtgDeviceAdapter(Device):
    """Adapter for ServiceNow configuration items to PRTG devices. Recommended 
    to use the classmethod from_ci to instantiate this class."""
    ci: ConfigItem
    default_name_format_key = 'ip only'

    @classmethod
    def from_ci(cls, ci: ConfigItem, format_key: str | None = None):
        if format_key:
            name_format = FORMAT_MAP[format_key]
            # check for required attributes
            missing_fields = _check_required_fields(ci, name_format)
            if missing_fields:
                logger.warning(f'Missing required fields for name format: {", ".join(missing_fields)} for {ci.name}. Falling back to "{cls.default_name_format_key}" name format.')
                name_format = FORMAT_MAP[cls.default_name_format_key]
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


class FieldGroup(ABC):
    """ConfigItems are organized by its field values, so FieldGroups are rules 
    to structure the tree at each level. A FieldGroup defines a function 
    get_group to determine which group it belongs to and the next FieldGroup to 
    follow."""
    @abstractmethod
    def get_group(self, ci:ConfigItem) -> tuple[str, Node]:
        pass


class ValueFieldGroup(FieldGroup):
    """Represents a group organized by the value itself."""
    def __init__(self, field_name: str, child: FieldGroup | None = None, children_map: Mapping[str, FieldGroup] | None = None):
        """
        Args:
            field_name(str): name of attribute
            child(FieldGroup | None): next FieldGroup to follow. Cannot be set alongside children_map. Defaults to None.
            children_map(Mapping[str, FieldGroup] | None): mapping of next FieldGroup depending on field value.
                Cannot be set alongside child. Defaults to None.
        """
        self.field_name = field_name
        self.child = child
        self.children_map = children_map

    def get_group(self, ci: ConfigItem):
        value = getattr(ci, self.field_name)
        child = self.child  # default to child attribute
        if self.children_map:
            try:
                child = self.children_map[value]  # update only if children_map was set
            except KeyError:
                pass
        return (value, child)


class BooleanFieldGroup(FieldGroup):
    """Represents a group organized by a boolean field."""
    def __init__(self,
                 field_name: str,
                 t_group_name: str,
                 f_group_name: str,
                 t_child: FieldGroup | None = None,
                 f_child: FieldGroup | None = None):
        """
        Args:
            field_name(str): name of attribute
            t_group_name(str): name of group if attribute value is True
            f_group_name(str): name of group if attribute value is False
            t_child(FieldGroup | None): next FieldGroup if value is True. Defaults to None.
            f_child(FieldGroup | None): next FieldGroup if value is False. Defaults to None.
        """
        self.field_name = field_name
        self.t_group_name = t_group_name
        self.f_group_name = f_group_name
        self.t_child = t_child
        self.f_child = f_child

    def get_group(self, ci: ConfigItem):
        value = getattr(ci, self.field_name)
        return (self.t_group_name, self.t_child) if value else (self.f_group_name, self.f_child)


class ChoiceSetFieldGroup(FieldGroup):
    """Represents a group organized by a choice set field."""
    def __init__(self, 
                 field_name: str,
                 choices: Set[str],
                 group_name: str,
                 child: FieldGroup | None = None,
                 children_map: Mapping[str, FieldGroup] | None = None):
        """
        Args:
            field_name(str): name of attribute
            choices(Set[str]): set of choices
            group_name(str): name of group if attribute value is one of the choices
            child(FieldGroup | None): next FieldGroup to follow. Cannot be set alongside children_map. Defaults to None.
            children_map(Mapping[str, FieldGroup] | None): mapping of next FieldGroup depending on field value.
                Cannot be set alongside child. Defaults to None.
        """
        self.field_name = field_name
        self.choices = choices
        self.group_name = group_name
        if child and children_map:
            raise ValueError('child and children_map attributes are mutually exclusive.')
        self.child = child
        self.children_map = children_map

    def get_group(self, ci: ConfigItem):
        """
        Returns:
            str: when attribute value is in choices
            None: when attribute value is not in choices
        """
        value = getattr(ci, self.field_name)
        child = self.child  # default to child attribute
        if self.children_map:
            try:
                child = self.children_map[value]  # update only if children_map was set
            except KeyError:
                pass
        return (self.group_name, child) if value in self.choices else (None, child)


class MultiChoiceSetFieldGroup(FieldGroup):
    """Represents a group organized by multiple choice set field groups."""
    def __init__(self, choiceset_field_groups: Iterable[ChoiceSetFieldGroup]):
        """
        Args:
            choiceset_field_groups(Iterable[ChoiceSetFieldGroup]): list of ChoiceSetFieldGroups
        """
        self.choiceset_field_groups = choiceset_field_groups

    @classmethod
    def from_dict(cls, field_name: str, field_groups_dict: Mapping[str, Iterable[str]]):
        return cls((ChoiceSetFieldGroup(field_name, set(choices), group_name) for group_name, choices in field_groups_dict.items()))

    def get_group(self, ci: ConfigItem):
        """
        Returns:
            str: when attribute value is in choices
            None: when attribute value is not in choices
        """
        for field_group in self.choiceset_field_groups:
            group_name, child = field_group.get_group(ci)
            if group_name is not None:
                return (group_name, child)
        return (None, None)  # no matches found


class TreeBuilder:
    def __init__(self, root: Node, levels: FieldGroup, group_name_fmt: str | None = None, device_name_fmt_key: str | None = None):
        self.root = root
        self.levels = levels
        self.group_name_fmt = group_name_fmt
        self.device_name_fmt_key = device_name_fmt_key

    def add_ci(self, ci: ConfigItem):
        parent = self.root  # track parent in loop
        current_level = self.levels # track current level
        while current_level:
            group_name, current_level = current_level.get_group(ci)  # get name and next level
            if group_name is None:
                # no matches for group, simply add to current group
                break
            if self.group_name_fmt is not None:
                group_name = self.group_name_fmt.format(group_name)  # format group name
            try:
                next_subgroup = next(node for node in parent.children if node.prtg_obj.name == group_name)
            except StopIteration:
                # subgroup does not exist, create it
                next_subgroup = Node(PrtgGroupAdapter(group_name), parent=parent)
            
            parent = next_subgroup  # update current parent
        return Node(PrtgDeviceAdapter.from_ci(ci, self.device_name_fmt_key), parent=parent)


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

    # organize subgroups by sys_class_name
    # keys are subgroup names and values are list of matching sys_class_names
    server_class_map = {
        'Out of Band Management': ['Out of Band Management'],
        'Windows Server': ['Windows Server'],
        'Linux Server': ['Linux Server'],
        'Application Server': ['Application Server']
    }

    network_class_map = {
        'IP Switch': ['Switch', 'IP Switch', 'IP Switch Cluster'],
        'APs': ['Wireless Access Point'],
        'IP Router': ['IP Router', 'Router', 'Internet Gateway'],
        'Firewall': ['Firewall Manager', 'Firewall Hardware', 'Software Firewall', 'Firewall Device']
    }

    storage_class_map = {
        'Storage Device': ['Storage Device'],
        'Storage Controller': ['Storage Controller'],
        'Storage Cluster': ['Storage Cluster'],
        'Storage Node': ['Storage Node'],
        'Storage Switch': ['Storage Switch']
    }

    virt_class_map = {
        'vCenter': ['VMware vCenter Instance'],
        'Hypervisor': ['ESX Server', 'Hyper-V Server'],
        'Virtual Machine': ['Virtual Machine Instance', 'VMware Virtual Machine Instance', 'Windows Server', 'Linux Server', 'MS SQL DataBase', 'Application Server'],
    }

    hardware_class_map = {
        'PDU': ['PDU'],
        'UPS': ['UPS']
    }

    # create field groups for organizing tree. Build in reverse order to attach child nodes
    server_class_group = MultiChoiceSetFieldGroup.from_dict('sys_class', server_class_map)
    network_class_group = MultiChoiceSetFieldGroup.from_dict('sys_class', network_class_map)
    storage_class_group = MultiChoiceSetFieldGroup.from_dict('sys_class', storage_class_map)
    virt_class_group = MultiChoiceSetFieldGroup.from_dict('sys_class', virt_class_map)
    hardware_class_group = MultiChoiceSetFieldGroup.from_dict('sys_class', hardware_class_map)
    category_map = {
        'Server': server_class_group,
        'Network': network_class_group,
        'Storage': storage_class_group,
        'Virtualization': virt_class_group,
        'Hardware': hardware_class_group
    }
    category_group = ValueFieldGroup('category', children_map=category_map)
    stage_group = ValueFieldGroup('stage', child=category_group)
    is_internal_group = BooleanFieldGroup('is_internal', 'CC Infrastructure', 'Customer Managed Infrastructure', f_child=stage_group)

    tree_builder = TreeBuilder(site, is_internal_group, group_name_fmt, company.prtg_device_name_format)
    for ci in config_items:
        tree_builder.add_ci(ci)
    return root
