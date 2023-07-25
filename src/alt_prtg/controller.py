from typing import Dict, List, Union

from prtg import ApiClient, Icon

from .models import Device, Group, Node, Probe, Status

class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_probe(self, id: Union[int, str]):
        probe = self.client.get_probe(id)
        return Probe(probe['objid'], probe['name'])

    def _get_group(self, group: Dict) -> Group:
        """Helper function to create a Group from a dict payload returned by the API"""
        tags = group['tags'].split()
        return Group(group['objid'], group['name'], group['priority'], tags, group['location'], Status(group['status']), group['active'])
              
    def get_group(self, id: Union[int, str]):
        group = self.client.get_group(id)
        return self._get_group(group)

    def get_group_by_name(self, name: str):
        groups = self.client.get_groups_by_name_containing(name)
        if len(groups) > 1:
            raise ValueError(f'More than one group found with name {name}.')
        try:
            group = groups[0]
        except IndexError:
            raise ValueError(f'No group found with name {name}.')
        return self._get_group(group)

    def add_group(self, group: Group, parent: Union[Probe, Group]) -> Group:
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
        return Device(device['objid'], device['name'], device['host'], service_url, device['priority'], tags, device['location'], icon, Status(device['status'].lower()), device['active'])

    def get_device(self, id) -> Device:
        device = self.client.get_device(id)
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
        return Device(device_id, device.name, device.host, device.service_url, device.priority, device.tags, device.location, device.icon, device.status, device.is_active)

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
        
        # Note that this does not call internal methods because the internal
        # device model does not store parent ID. Like the other methods, it
        # will use client methods and take advantage of the 'parentid' attribute.

        # Get all devices in root group.
        devices_dict = self.client.get_devices_by_group_id(group.id)

        # Work backwards, creating groups until the root group is reached
        group_map = {group.id: root}  # map ID with created nodes to avoid duplicates
        for device_dict in devices_dict:
            device = self._get_device(device_dict)
            curr_node = Node(device)
            parent_id = device_dict['parentid']
            while True:
                try:
                    existing_node = group_map[parent_id]
                except KeyError:
                    # Node does not exist. Create new node, update new node as parent of
                    # current node, and make the node the new current node.
                    sub_group_dict = self.client.get_group(parent_id)   # Get group details
                    sub_group = self._get_group(sub_group_dict)
                    new_node = Node(sub_group)
                    curr_node.parent = new_node         # Update node's parent
                    group_map[parent_id] = new_node     # Add new node to map
                    
                    # Update current details
                    curr_node = new_node
                    parent_id = sub_group_dict['parentid']
                    continue
                # Node exists, simply update parent node
                curr_node.parent = existing_node
                break
        return root
