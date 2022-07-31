import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

class PrtgApi:
    id_pattern = re.compile('(?<=(\?|&)id=)\d+')

    def __init__(self, 
            url: str, 
            username: str, 
            password: str, 
            template_group: int = None, 
            template_device: int = None, 
            passhash: bool = True):
        self.url = url
        self.template_group = template_group
        self.template_device = template_device

        key = 'passhash' if passhash else 'password'
        self.auth = {'username': username, key: password}
        
        self._validate_cred()
    
    def _validate_cred(self):
        url = self.url + '/api/healthstatus.json'
        response = requests.get(url, self.auth)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise requests.HTTPError('Unauthorized') if response.status_code == 401 else e

    def _parse_obj_id(self, url):
        return PrtgApi.id_pattern.match(urllib.parse.unquote(url), re.I).group(0)

    def device_url(self, id):
        return f'{self.url}/device.htm?id={id}'

    # Probes

    def _get_probes_base(self, **params):
        url = self.url + '/api/table.json'
        params = {
            'content': 'probes',
            'filter_parentid': 0,
            'columns': 'objid,name,active,tags,parentid,priority,\
                        status,groupnum,devicenum,location'
        }
        params.update(self.auth)
        params.update(params)
        response = requests.get(url, params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code == 400:
                root = ET.fromstring(response.text)
                error_msg = root.find('error').text
                raise requests.HTTPError(error_msg)
            raise e
        return response.json()['probes']

    def get_all_probes(self):
        return self._get_probes_base()

    def get_probe_by_name(self, name):
        return self._get_probes_base(filter_name=name)

    def get_probe(self, id):
        return self._get_probes_base(filter_objid=id)

    # Groups

    def _get_groups_base(self, **params):
        url = self.url + '/api/table.json'
        params = {
            'content': 'groups',
            'columns': 'objid,name,active,status,probe,priority,\
                        tags,location,parentid,groupnum,devicenum'
        }
        params.update(self.auth)
        params.update(params)
        response = requests.get(url, params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code == 400:
                root = ET.fromstring(response.text)
                error_msg = root.find('error').text
                raise requests.HTTPError(error_msg)
            raise e
        return response.json()['groups']

    def get_all_groups(self):
        return self._get_groups_base()

    def get_group(self, id):
        return self._get_groups_base(filter_objid=id)

    def add_group(self, name, group_id):
        url = self.url + '/api/duplicateobject.htm'
        params = {
            'id': self.template_group,
            'name': name,
            'targetid': group_id
        }
        params.update(self.auth)
        response = requests.get(url, params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code == 400:
                root = ET.fromstring(response.text)
                error_msg = root.find('error').text
                raise requests.HTTPError(error_msg)
            raise e
        return self._parse_obj_id(response.url)

    # Devices

    def _get_devices_base(self, **params):
        url = self.url + '/api/table.json'
        params = {
            'content': 'devices',
            'columns': 'objid,name,active,status,probe,group,host,\
                        priority,tags,location,parentid'
        }
        params.update(self.auth)
        params.update(params)
        response = requests.get(url, params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code == 400:
                root = ET.fromstring(response.text)
                error_msg = root.find('error').text
                raise requests.HTTPError(error_msg)
            raise e
        return response.json()['devices']

    def get_all_devices(self):
        return self._get_devices_base()

    def get_devices_by_group_id(self, group_id):
        return self._get_devices_base(id=group_id)

    def get_device(self, id):
        return self._get_devices_base(filter_objid=id)

    def add_device(self, name, host, group_id):
        url = self.url + '/api/duplicateobject.htm'
        params = {
            'id': self.template_device,
            'name': name,
            'host': host,
            'targetid': group_id
        }
        params.update(self.auth)
        response = requests.get(url, params)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code == 400:
                root = ET.fromstring(response.text)
                error_msg = root.find('error').text
                raise requests.HTTPError(error_msg)
            raise e
        return self._parse_obj_id(response.url)

    # Object Status

    def _get_obj_status_base(self, id, property):
        url = self.url + '/api/getobjectstatus.htm'
        params = {
            'id': id,
            'name': property,
            'show': 'nohtmlencode'
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        return root.find('result').text

    # Object Property

    def _get_obj_property_base(self, id, property):
        url = self.url + '/api/getobjectproperty.htm'
        params = {
            'id': id,
            'name': property,
            'show': 'nohtmlencode'
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()
        tree = ET.fromstring(response.content)
        return tree.find('result').text

    def _set_obj_property_base(self, id, name, value):
        url = self.url + '/api/setobjectproperty.htm'
        params = {
            'id': id,
            'name': name,
            'value': value
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()

    def set_icon(self, id, icon):
        self._set_obj_property_base(id, 'deviceicon', icon)

    def set_location(self, id, location):
        self._set_obj_property_base(id, 'location', location)

    def set_service_url(self, id, url):
        self._set_obj_property_base(id, 'serviceurl', url)

    def set_tags(self, id, tags):
        # api accepts each space-separated word as a tag
        combined_tags = ' '.join(tags)
        self._set_obj_property_base(id, 'tags', combined_tags)

    def set_inherit_location_off(self, id):
        return self._set_obj_property_base(id, 'locationgroup_', 0)

    def set_inherit_location_on(self, id):
        return self._set_obj_property_base(id, 'locationgroup_', 1)

    # Actions

    def pause_object(self, id):
        url = self.url + '/api/pause.htm'
        params = {
            'id': id,
            'action': 0
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()

    def resume_object(self, id):
        url = self.url + '/api/pause.htm'
        params = {
            'id': id,
            'action': 1
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()

    def delete_object(self, id):
        url = self.url + '/api/deleteobject.htm'
        params = {
            'id': id,
            'approve': 1
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()

    def set_priority(self, id, value):
        if value < 1 or value > 5:
            raise ValueError('Priorty can only set between 0 - 5.')
        url = self.url + '/api/setpriority.htm'
        params = {
            'id': id,
            'prio': value
        }
        params.update(self.auth)
        response = requests.get(url, params)
        response.raise_for_status()
