from typing import Dict, List, Union

from prtg import ApiClient, Icon
from prtg.exception import ObjectNotFound

from .models import Device, Group, Node, Status


class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_probe(self, probe_id: Union[int, str]) -> Group:
        """Probes will be treated the same as groups"""
        probe = self.client.get_probe(probe_id)
        return self._get_group(probe)

    def _get_group(self, group: Dict) -> Group:
        """Helper function to create a Group from a dict payload returned by the API"""
        tags = group['tags'].split()
        return Group(group['objid'], group['name'], group['priority'], tags, group['location'], Status(group['status'].lower()), group['active'])

    def get_group(self, group_id: Union[int, str]) -> Group:
        group = self.client.get_group(group_id)
        return self._get_group(group)

    def get_group_by_name(self, name: str) -> Group:
        groups = self.client.get_groups_by_name_containing(name)
        if len(groups) > 1:
            raise ValueError(f'More than one group found with name {name}.')
        try:
            group = groups[0]
        except IndexError:
            raise ValueError(f'No group found with name {name}.')
        return self._get_group(group)

    def add_group(self, group: Group, parent: Group) -> Group:
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may not be created yet.')
        new_group = self.client.add_group(group.name, parent.id)
        group_id = new_group['objid']
        if group.is_active:
            self.client.resume_object(group_id)
        else:
            self.client.pause_object(group_id)
        self.client.set_priority(group_id, group.priority)
        if group.tags:
            self.client.set_tags(group_id, group.tags)
        if group.location:
            self.client.set_location(group_id, group.location)
        return Group(group_id, group.name, group.priority, group.tags, group.location, group.status, group.is_active)

    def _get_device(self, device: Dict) -> Device:
        """Helper function to create a Device from a dict payload returned by the API"""
        tags = device['tags'].split()
        try:
            icon = Icon(device['icon'])
        except ValueError:
            icon = None
        service_url = self.client.get_service_url(device['objid'])
        return Device(device['objid'], device['name'], device['host'], service_url, device['priority'], tags, device['location'], icon,
                      Status(device['status'].lower()), device['active'])

    def get_device(self, device_id) -> Device:
        device = self.client.get_device(device_id)
        return self._get_device(device)

    def add_device(self, device: Device, parent: Group) -> Device:
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may not be created yet.')
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
            self.client.set_tags(device_id, device.tags)
        if device.location:
            self.client.set_location(device_id, device.location)
        return Device(device_id, device.name, device.host, device.service_url, device.priority, device.tags, device.location, device.icon, device.status,
                      device.is_active)

    def get_devices_in_group(self, parent: Group) -> List[Device]:
        if parent.id is None:
            raise ValueError(f'Group "{parent.name}" is missing required attribute id. This group may not be created yet.')
        devices = self.client.get_devices_by_group_id(parent.id)
        return [self._get_device(device) for device in devices]

    def get_tree(self, group: Group) -> Node:
        """Create a tree model of a group in PRTG. There exists a get_sensortree() endpoint
        but this avoids parsing an XML tree as well as pulling all sensor data which isn't
        currently needed."""
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
