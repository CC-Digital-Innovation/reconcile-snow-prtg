from typing import Union

from prtg import ApiClient

from .models import Device, Group, Status

class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_group(self, id: Union[int, str]):
        group = self.client.get_group(id)
        tags = group['tags'].split()
        return Group(group['objid'], group['name'], group['parentid'], group['priority'], tags, group['location'], Status(group['status']), group['active'])

    def get_group_by_name(self, name: str):
        groups = self.client.get_groups_by_name_containing(name)
        if len(groups) > 1:
            raise ValueError(f'More than one group found with name {name}.')
        try:
            group = groups[0]
        except IndexError:
            raise ValueError(f'No group found with name {name}.')
        tags = group['tags'].split()
        return Group(group['objid'], group['name'], group['parentid'], group['priority'], tags, group['location'], Status(group['status'].lower()), group['active'])

    def add_group(self, group: Group) -> Group:
        new_group = self.client.add_group(group.name, group.parent_id)
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
        return Group(group_id, group.name, group.parent_id, group.priority, group.tags, group.location, group.status, group.is_active)

    def get_device(self, id):
        device = self.client.get_device(id)
        tags = device['tags'].split()
        service_url = self.client.get_service_url(id)
        return Device(device['objid'], device['name'], device['host'], service_url, device['parentid'], device['priority'], tags, device['location'], device['icon'], Status(device['status'].lower()), device['active'])

    def add_device(self, device: Device) -> Device:
        if device.parent_id is None:
            raise ValueError(f'Device "{device.name}" is missing required attribute parent_id.')
        if device.icon:
            new_device = self.client.add_device(device.name, device.host, device.parent_id, device.icon)
        else:
            new_device = self.client.add_device(device.name, device.host, device.parent_id)
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
        return Device(device_id, device.name, device.host, device.service_url, device.parent_id, device.priority, device.tags, device.location, device.icon, device.status, device.is_active)
