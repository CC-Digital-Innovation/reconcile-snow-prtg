from prtg import ApiClient, Icon
from prtg.exception import ObjectNotFound

from .models import Device, Group, Node, Status

import copy

class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_probe(self, probe_id: int | str) -> Group:
        """Probes will be treated the same as groups"""
        probe = self.client.get_probe(probe_id)
        return self._get_group(probe)

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

    def get_group_by_name(self, name: str, parent_id: int | str | None = None) -> Group:
        """Get a group by its name. Optionally filter by an ancestor group by its ID.

        Args:
            name (str): name of group
            parent_id (int | str | None, optional): filter by ancestor group ID. Defaults to None.

        Raises:
            ValueError: when no group found with name

        Returns:
            Group
        """
        groups = self.client.get_groups_by_name_containing(name, parent_id)
        try:
            group = groups[0]
        except IndexError:
            raise ValueError(f'No group found with name {name}.')
        return self._get_group(group)

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
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may have not be created yet.')
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
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may have not be created yet.')
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

    def get_devices_in_group(self, parent: Group) -> list[Device]:
        """Get all devices in a group

        Args:
            parent (Group): parent group to get all devices from

        Raises:
            ValueError: when parent group does not exist

        Returns:
            list[Device]
        """
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may have not be created yet.')
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

    def get_path_group_to_object(self, group: Group, object: Device | Group):
        """Get a node tree from group to specified object

        Args:
            group (Group): group, ancestor of object
            object (Device | Group): object, descendant of group

        Raises:
            ValueError: when group or object ID is missing

        Returns:
            Node: tree from group to object
        """
        if group.id is None:
            raise ValueError(f'Cannot get path from group, group ID is missing for group {group.name}')
        if object.id is None:
            raise ValueError(f'Cannot get path from object, object ID is missing for object {object.name}')

        # get object details to obtain parent ID
        if isinstance(object, Device):
            object_dict = self.client.get_device(object.id)
        elif isinstance(object, Group):
            object_dict = self.client.get_group(object.id)
        else:
            raise NotImplementedError(f'Object type {type(object)} is not supported.')
        
        intermediate_nodes = [] # stack of nodes between group and object to get
        ancestor_id = object_dict['parentid']
        # loop through ancestors of object until group
        while True:
            if ancestor_id == group.id:
                break
            if ancestor_id < 0:
                raise ValueError('Could not find group on path.')
            # get group details to obtain parent ID
            try:
                intermediate_group_dict = self.client.get_group(ancestor_id)
            except ObjectNotFound:
                intermediate_group_dict = self.client.get_probe(ancestor_id)  # Probe group
            intermediate_group = self._get_group(intermediate_group_dict)
            intermediate_nodes.append(intermediate_group)
            ancestor_id = intermediate_group_dict['parentid']  # update current parent ID
        
        # build path
        root = Node(group)
        current_parent_node = root
        while intermediate_nodes:
            current_child = intermediate_nodes.pop()  # pop from stack as order is in reverse
            current_child_node = Node(current_child, current_parent_node)
            current_parent_node = current_child_node
        Node(object, current_parent_node)  # last parent node is object's parent
        return root

    def move_object(self, object: Device | Group, parent: Group):
        """Move an object

        Args:
            object (Device | Group): object to move
            parent (Group): parent group where object is moved

        Raises:
            ValueError: when object or parent group ID is missing
        """
        if object.id is None:
            raise ValueError(f'Cannot move object, object ID is missing for object {object.name}')
        if parent.id is None:
            raise ValueError(f'Cannot move to group, group ID is missing for group {parent.name}')
        self.client.move_object(object.id, parent.id)

    def delete_object(self, object: Device | Group):
        """Delete an object

        Args:
            object (Device | Group): object to be deleted

        Raises:
            ValueError: object is missing ID field
        """
        if object.id is None:
            raise ValueError(f'Cannot delete object, object ID is missing for object {object.name}')
        self.client.delete_object(object.id)

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

    def set_device_properties(self, objid: str | int, hostname: str | None = None, name_update: str | None = None, location: str | None = None):
        if hostname:
            self.client.set_hostname(objid, hostname)
        
        if name_update:
            self.client._set_obj_property_base(objid, 'name', name_update)
        
        if location:
            self.client.set_inherit_location_off(objid)
            self.client.set_location(objid, location)


    def moveobj_setproperties_deleteobj(self, snow_data, objid : str | int, parent_group : dict):
            
            name_update = snow_data.manufactuer_model + " " + snow_data.manufacturer_number + " (" + str(snow_data.ip) + ")"
            
            # Make copies for deletion of group if empty
            groupid_copy = copy.deepcopy(parent_group['objid'])         
            grandparent_groupid_copy = copy.deepcopy(parent_group['parentid'])

            self.client.move_object(snow_data.objid, objid) 
            self.set_device_properties(snow_data.objid, snow_data.hostname, name_update, snow_data.location)


            if self.client.get_devices_by_group_id(groupid_copy) == []:
                self.client.delete_object(groupid_copy)
            if self.client.get_devices_by_group_id(grandparent_groupid_copy) == []:
                self.client.delete_object(grandparent_groupid_copy)
