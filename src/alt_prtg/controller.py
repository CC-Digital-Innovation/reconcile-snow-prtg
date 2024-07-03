from prtg import ApiClient, Icon
from prtg.exception import ObjectNotFound

from .models import Device, Group, Node, Status


class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_probe(self, probe_id: int | str) -> Group:
        """Probes will be treated the same as groups"""
        probe = self.client.get_probe(probe_id)
        return self._get_group(probe)

    def get_probe_by_name(self, name: str) -> Group:
        """Get a probe by its name.
        
        Args:
            name (str): name of probe
            
        Raises:
            ValueError: no probe found with name or multiple probes found with name
            
        Returns:
            Group: probes will be treated the same as groups
        """
        probes = self.client.get_probes_by_name_containing(name)
        # due to client.get_probes_by_name_containing() accepting probes with name as substring,
        # manually compare exact match to get probe
        probes = [probe for probe in probes if probe['name'] == name]
        if len(probes) == 0:
            raise ValueError(f'No probe found with name {name}.')
        if len(probes) > 1:
            raise ValueError(f'More than one probe found with name {name}.')
        return self._get_group(probes[0])

    def _get_group(self, group: dict) -> Group:
        """Helper function to create a Group from a dict payload returned by the API"""
        tags = set(group['tags'].split())
        return Group(group['objid'], group['name'], int(group['priority']), tags, group['location'], Status(group['status'].lower()), group['active'])

    def get_group(self, group_id: int | str) -> Group:
        """Get group by id

        Args:
            group_id (int | str): id of group

        Returns:
            Group
        """
        group = self.client.get_group(group_id)
        return self._get_group(group)

    def get_group_by_name(self, name: str, parent: Group | None = None) -> Group:
        """Get a group by its name. Optionally filter by an ancestor group by its ID.

        Args:
            name (str): name of group
            parent (Group | None, optional): filter by ancestor group. Defaults to None.

        Raises:
            ValueError: when parent group is missing ID, no group found with name, multiple groups found with name

        Returns:
            Group
        """
        if parent is not None:
            if parent.id is None:
                raise ValueError(f'Group {parent.name} is missing required attribute id.')
            parent_id = parent.id
        else:
            parent_id = None
        # client.get_group_by_name() does not work with names containing square brackets ([]),
        # use client.get_groups_by_name_containing() instead
        groups = self.client.get_groups_by_name_containing(name, parent_id)
        # due to client.get_groups_by_name_containing() accepting groups with name as substring,
        # manually compare exact match to get group
        groups = [group for group in groups if group['name'] == name]
        if len(groups) == 0:
            raise ValueError(f'No group found with name {name}.')
        if len(groups) > 1:
            raise ValueError(f'More than one group found with name {name}.')
        return self._get_group(groups[0])

    def add_group(self, group: Group, parent: Group) -> Group:
        """Add a group

        Args:
            group (Group): group to add
            parent (Group): parent group where new group is added

        Raises:
            ValueError: when parent group does not exist

        Returns:
            Group: new group
        """
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id.')
        new_group = self.client.add_group(group.name, parent.id)
        group_id = new_group['objid']
        if group.is_active:
            self.client.resume_object(group_id)
        else:
            self.client.pause_object(group_id)
        self.client.set_priority(group_id, group.priority)
        if group.tags:
            self.client.set_tags(group_id, list(group.tags))
        if group.location:
            self.client.set_location(group_id, group.location)
        return Group(group_id, group.name, group.priority, group.tags, group.location, group.status, group.is_active)

    def get_groups(self, parent: Group | None = None) -> list[Group]:
        """Get groups, optionally filtered by a parent group

        Args:
            parent (Group | None, optional): return only groups from this parent. Defaults to None.

        Raises:
            ValueError: when parent group is missing ID field

        Returns:
            list[Group]
        """
        if parent is None:
            groups = self.client.get_all_groups()
        else:
            if parent.id is None:
                raise ValueError(f'Group {parent.name} is missing required attribute id.')
            groups = self.client.get_groups_by_group_id(parent.id)
        return [self._get_group(group) for group in groups]

    def get_groups_by_name(self, name: str, parent: Group | None = None) -> list[Group]:
        """Get groups with name, optionally filtered by a parent group

        Args:
            name (str): name of group(s)
            parent (Group | None, optional): return only groups from this parent. Defaults to None.

        Raises:
            ValueError: when parent group is missing ID field

        Returns:
            list[Group]
        """
        if parent is not None:
            if parent.id is None:
                raise ValueError(f'Group {parent.name} is missing required attribute id.')
            parent_id = parent.id
        else:
            parent_id = None
        groups = self.client.get_groups_by_name_containing(name, parent_id)
        return [self._get_group(group) for group in groups]

    def _get_device(self, device: dict) -> Device:
        """Helper function to create a Device from a dict payload returned by the API"""
        tags = set(device['tags'].split())
        try:
            icon = Icon(device['icon'])
        except ValueError:
            icon = None
        service_url = self.client.get_service_url(device['objid'])
        return Device(device['objid'], device['name'], device['host'], service_url, int(device['priority']), tags, device['location'], icon,
                      Status(device['status'].lower()), device['active'])

    def get_device(self, device_id: int | str) -> Device:
        """Get a device by its id

        Args:
            device_id (int | str): id of device

        Returns:
            Device
        """
        device = self.client.get_device(device_id)
        return self._get_device(device)

    def add_device(self, device: Device, parent: Group) -> Device:
        """Add a device

        Args:
            device (Device): device to add
            parent (Group): parent group where device is added

        Raises:
            ValueError: when parent group does not exist

        Returns:
            Device: new device
        """
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id.')
        if device.icon:
            new_device = self.client.add_device(device.name, device.host, parent.id, device.icon)
        else:
            new_device = self.client.add_device(device.name, device.host, parent.id)
        device_id = new_device['objid']
        if device.service_url:
            self.client.set_service_url(device_id, device.service_url)
        if device.is_active:
            self.client.resume_object(device_id)
        else:
            self.client.pause_object(device_id)
        self.client.set_priority(device_id, device.priority)
        if device.tags:
            self.client.set_tags(device_id, list(device.tags))
        if device.location:
            self.client.set_location(device_id, device.location)
        return Device(device_id, device.name, device.host, device.service_url, device.priority, device.tags, device.location, device.icon, device.status,
                      device.is_active)

    def get_devices(self, parent: Group | None = None) -> list[Device]:
        """Get all devices, optionally filtered by parent group.

        Args:
            parent (Group | None, optional): parent group to get all devices from. Defaults to None.

        Raises:
            ValueError: when parent group does not exist

        Returns:
            list[Device]:
        """
        if parent is None:
            devices = self.client.get_all_devices()
        else:
            if parent.id is None:
                raise ValueError(f'Group "{parent.name}" is missing required attribute id.')
            devices = self.client.get_devices_by_group_id(parent.id)
        return [self._get_device(device) for device in devices]

    def update_device(self, device: Device):
        """Update a device

        Args:
            device (Device): device with updated fields

        Raises:
            ValueError: when device is missing ID field
        """
        if device.id is None:
            raise ValueError(f'Cannot update device, ID is missing for device {device.name}')
        current_device = self.get_device(device.id)
        if device.name != current_device.name:
            self.client.rename_object(device.id, device.name)
        if device.host != current_device.host:
            self.client.set_hostname(device.id, device.host)
        if device.service_url != current_device.service_url:
            self.client.set_service_url(device.id, device.service_url)
        if device.priority != current_device.priority:
            self.client.set_priority(device.id, device.priority)
        if device.tags != current_device.tags:
            self.client.set_tags(device.id, list(device.tags))
        if device.icon and device.icon != current_device.icon:
            self.client.set_icon(device.id, device.icon)

    def get_parent(self, obj: Device | Group) -> Group:
        """Get object's parent

        Args:
            obj (Device | Group): object to return parent of

        Raises:
            ValueError: when object ID is missing or obj is not a device or group

        Returns:
            Group
        """
        if obj.id is None:
            raise ValueError(f'Cannot get parent, object ID is missing for object {obj.name}')
        if isinstance(obj, Device):
            obj_dict = self.client.get_device(obj.id)
        elif isinstance(obj, Group):
            try:
                obj_dict = self.client.get_group(obj.id)
            except ObjectNotFound:
                # object could be a probe
                obj_dict = self.client.get_probe(obj.id)
        else:
            raise ValueError(f'Unsupported type {type(obj)}')
        try:
            group = self.client.get_group(obj_dict['parentid'])
        except ObjectNotFound:
            # parent could be a probe
            group = self.client.get_probe(obj_dict['parentid'])
        return self._get_group(group)

    def move_object(self, obj: Device | Group, parent: Group):
        """Move an object

        Args:
            obj (Device | Group): object to move
            parent (Group): parent group where object is moved

        Raises:
            ValueError: when object or parent group ID is missing
        """
        if obj.id is None:
            raise ValueError(f'Cannot move object, object ID is missing for object {obj.name}')
        if parent.id is None:
            raise ValueError(f'Cannot move to group, group ID is missing for group {parent.name}')
        self.client.move_object(obj.id, parent.id)

    def delete_object(self, obj: Device | Group):
        """Delete an object

        Args:
            obj (Device | Group): object to be deleted

        Raises:
            ValueError: object is missing ID field
        """
        if obj.id is None:
            raise ValueError(f'Cannot delete object, object ID is missing for object {obj.name}')
        self.client.delete_object(obj.id)

    def get_tree(self, group: Group) -> Node:
        """Create a tree model of a group in PRTG. There exists a get_sensortree() endpoint
        but this avoids parsing an XML tree as well as pulling all sensor data which isn't
        currently needed.
        
        Args:
            group (Group): base root of tree
        
        Raises:
            ValueError: group is missing ID field
        
        Returns:
            Node: root node
        """
        if group.id is None:
            raise ValueError(f'Group "{group.name}" is missing required attribute id. This group may not be created yet.')
        # Initialize argument group as root node
        root = Node(group)
        # map {id: Node} to avoid creating duplicate nodes
        group_map = {group.id: root}

        # Note that this does not call internal methods because the internal
        # device model does not store parent ID. Like the other methods, it
        # will use client methods but will take advantage of the 'parentid'
        # attribute.

        # Get all devices in root group.
        devices = self.client.get_devices_by_group_id(group.id)

        # Build tree backward from leaf nodes, i.e. devices
        for device_dict in devices:
            # ignore probe devices
            if device_dict['name'] == 'Probe Device':
                continue
            device = self._get_device(device_dict)
            nodes_to_create = [device]  # ordered list of nodes to create later
            curr_parent_id = device_dict['parentid']
            # Loop through parent groups using 'parentid' until existing Node is reached,
            # whether that's the root node or a previously created one
            while True:
                try:
                    existing_node = group_map[curr_parent_id]
                except KeyError:
                    # Node does not exist. Add new group to list of nodes to create
                    # and update current parent ID.
                    try:
                        sub_group_dict = self.client.get_group(curr_parent_id)   # Get group details
                    except ObjectNotFound:
                        # Probe group
                        sub_group_dict = self.client.get_probe(curr_parent_id)
                    sub_group = self._get_group(sub_group_dict)
                    nodes_to_create.append(sub_group)
                    curr_parent_id = sub_group_dict['parentid']
                    continue
                break
            # Create tree path downward, starting with existing node as parent
            for prtg_obj in reversed(nodes_to_create):
                new_node = Node(prtg_obj, parent=existing_node)
                group_map[prtg_obj.id] = new_node
                existing_node = new_node
        return root
