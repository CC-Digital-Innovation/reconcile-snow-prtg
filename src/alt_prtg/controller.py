from prtg import ApiClient

from .models import Group, Status

class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def add_group(self, name, parent_id, service_url='', priority=3, tags=None, location='', is_active=True) -> Group:
        group = self.client.add_group(name, parent_id)
        gid = group['objid']
        if service_url:
            self.client.set_service_url(gid, service_url)
        if is_active:
            self.client.resume_object(gid)
        else:
            self.client.pause_object(gid)
        self.client.set_priority(gid, priority)
        if tags:
            self.client.set_tags(tags)
        else:
            tags = []
        if location:
            self.client.set_location(gid, location)

        return Group(gid, name, parent_id, service_url, priority, tags, location, Status.UP, is_active)
