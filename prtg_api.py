import re
import urllib.parse
import xml.etree.ElementTree as ET
from enum import Enum

import requests
from loguru import logger

class PRTGInstance:
    def __init__(self, url, username, password, template_group, template_device, is_passhash=False):
        self.url = url
        self.username = username
        self.password = password
        self.is_passhash = is_passhash
        self.template_group = template_group
        self.template_device = template_device
        self.sensortree = self.get_sensortree()

    def get_sensortree(self):
        url = self.url + '/api/table.xml'
        params = {
            'username': self.username,
            'content': 'sensortree'
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        if response.status_code == 401:
            logger.warning('Username or password is incorrect.')
            raise ValueError('Username or password is incorrect.')
        else:
            response.raise_for_status
        return response.text

    def get_probe_id(self, company_name, site_name):
        # possible stale data using referenced sensortree
        name = f'[{company_name}] {site_name}'
        tree = ET.fromstring(self.sensortree)
        groups = []
        groups.extend(tree.iter('group'))
        groups.extend(tree.iter('probenode'))
        for element in groups:
            if element.find('name').text == name:
                return element.get('id')

    def get_obj_status(self, id, property):
        # different from get_obj_property, includes some property-like properties like parent ID
        url = self.url + '/api/getobjectstatus.htm'
        params = {
            'username': self.username,
            'id': id,
            'name': property,
            'show': 'nohtmlencode'
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        tree = ET.fromstring(response.text)
        try:
            result = tree.find('result').text
            return result
        except AttributeError:
            logger.error('Cannot find element result.')

    def get_obj_property(self, id, property):
        url = self.url + '/api/getobjectproperty.htm'
        params = {
            'username': self.username,
            'id': id,
            'name': property,
            'show': 'nohtmlencode'
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        tree = ET.fromstring(response.content)
        try:
            result = tree.find('result').text
            return result
        except AttributeError:
            logger.error('Cannot find element result.')

    def get_devices(self, group_id=None):
        '''Returns a list of all devices. If a group id is given,
        return a list of all devices only from that group.'''
        if group_id:
            logger.info(f'Getting all devices from group with id {group_id}')
        else:
            logger.info('Getting all devices')
        url = self.url + '/api/table.json'
        params = {
            'username': self.username,
            'content': 'devices',
            'columns': 'objid,name,active,device,group,priority,host,tags,location,parentid',
            'id': group_id
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        return response.json()['devices']

    def add_group(self, name, group_id):
        '''Adds a new group.'''
        logger.info(f'Adding group {name} to group with id {group_id}')
        url = self.url + '/api/duplicateobject.htm'
        params = {
            'username': self.username,
            'id': self.template_group,
            'name': name,
            'targetid': group_id
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        id = self._parse_obj_id(response.url)
        # an error will capture the template's id
        if str(id) != str(self.template_group):
            return id

    def add_device(self, name, group_id, host):
        '''Adds a new device.'''
        logger.info(f'Adding device {name} to group with id {group_id}')
        url = self.url + '/api/duplicateobject.htm'
        params = {
            'username': self.username,
            'id': self.template_device,
            'name': name,
            'host': host,
            'targetid': group_id
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        id = self._parse_obj_id(response.url)
        # an error will capture the template's id
        if str(id) != str(self.template_device):
            return id

    # TODO Consider template devices instantiated with sensors instead of duplicating sensors
    # def add_sensor(self, name, device_id):
    #     '''Adds a new sensor'''
    #     logger.info(f'Adding sensor {name} to device with id {device_id}')
    #     url = self.url + '/api/duplicateobject.htm'
    #     params = {
    #         'username': self.username,
    #         'id': self.template_sensor,
    #         'name': name,
    #         'targetid': device_id
    #     }
    #     if self.is_passhash:
    #         params['passhash'] = self.password
    #     else:
    #         params['password'] = self.password
    #     response = requests.get(url, params)
    #     response.raise_for_status
    #     id = self._parse_obj_id(response.url)
    #     # an error will capture the template's id
    #     if str(id) != str(self.template_sensor):
    #         return id

    def edit_obj_settings(self, id, name, value):
        '''Base api to change all object settings'''
        url = self.url + '/api/setobjectproperty.htm'
        params = {
            'username': self.username,
            'id': id,
            'name': name,
            'value': value
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status

    def edit_priority(self, id, value):
        '''Set object priority.'''
        if value < 1 or value > 5:
            raise ValueError('Priorty can only set between 1 - 5.')
        url = self.url + '/api/setpriority.htm'
        params = {
            'username': self.username,
            'id': id,
            'prio': value
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status

    def edit_icon(self, id, vendor, category=None):
        try:
            vendors = vendor.split('/')
            icon = self.Icons[vendors[0].upper()]
            self.edit_obj_settings(id, 'deviceicon', icon.value)
        except KeyError:
            logger.warning('Vendor not recognized, using category as fallback.')
            icon = self.Icons[category.upper()]
            self.edit_obj_settings(id, 'deviceicon', icon.value)

    def edit_location(self, id, location):
        self.edit_obj_settings(id, 'location', location)

    def edit_service_url(self, id, url):
        self.edit_obj_settings(id, 'serviceurl', url)

    def edit_tags(self, id, tags):
        '''OVERWRITES the tags of an object'''
        # api accepts each space-separated word as a tag
        combined_tags = ' '.join(tags)
        self.edit_obj_settings(id, 'tags', combined_tags)

    def edit_obj_inherit(self, id, inherit_type, value):
        '''Base api to switch off/on inheritance settings.
        Value accepts int 0 (off) or 1 (on).'''
        if value != 0 and value != 1:
            raise ValueError('Value can only be 0 or 1')
        url = self.url + '/editsettings'
        params = {
            'username': self.username,
            'id': id,
            inherit_type: value
        }
        if self.is_passhash:
            params['passhash'] = self.password
        else:
            params['password'] = self.password
        response = requests.get(url, params)
        response.raise_for_status
        return self._parse_obj_id(response.url)

    def edit_inherit_location(self, id, value):
        return self.edit_obj_inherit(id, 'locationgroup', value)

    def edit_cred_windows(self, id, domain_name, user_name, password):
        # domain_name can also be computer name if using local user account
        self.edit_obj_settings(id, 'windowsloginusername', user_name)
        self.edit_obj_settings(id, 'windowsloginpassword', password)
        self.edit_obj_settings(id, 'windowslogindomain', domain_name)

    def edit_cred_linux(self, id, user_name, password, private_key=False, wbem_http=False, wbem_port=None, ssh_port=None):
        self.edit_obj_settings(id, 'linuxloginusername', user_name)
        self.edit_obj_settings(id, 'linuxloginpassword', password)
        if private_key:
            self.edit_obj_settings(id, 'linuxloginmode', 1)
        if wbem_http:
            self.edit_obj_settings(id, 'wbemprotocol', 'http')
        if wbem_port:
            self.edit_obj_settings(id, 'wbemportmode', 1)
            self.edit_obj_settings(id, 'wbemport', wbem_port)
        if ssh_port:
            self.edit_obj_settings(id, 'sshport', ssh_port)

    def edit_cred_vmware(self, id, user_name, password, http=False):
        self.self.self.self.self.self.edit_obj_settings(id, 'esxuser', user_name)
        self.self.edit_obj_settings(id, 'esxpassword', password)
        if http:
            self.self.edit_obj_settings(id, 'esxprotocol', 1)

    def edit_cred_snmp(self, id, version, community_str, port):
        # acceptable version values are 'V1' | 'V2' | 'V3'
        self.edit_obj_settings(id, 'snmpversion', version)
        self.edit_obj_settings(id, 'snmpcommv2', community_str)
        self.edit_obj_settings(id, 'snmpport', port)

    def edit_cred_dbms(self, id, user_name, password, port=None, window_auth=False):
        if port:
            self.edit_obj_settings(id, 'usedbcustomport', 1)
            self.edit_obj_settings(id, 'dbport', port)
        if not window_auth:
            self.edit_obj_settings(id, 'dbauth', 1)
            self.edit_obj_settings(id, 'dbuser', user_name)
            self.edit_obj_settings(id, 'dbpassword', password)

    def edit_cred_aws(self, id, access_key, secret_key):
        self.edit_obj_settings(id, 'awsak', access_key)
        self.edit_obj_settings(id, 'awssk', secret_key)
        
    def edit_cred_dell_emc(self, id, user_name, password, port=None):
        self.edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-user', user_name)
        self.edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-password', password)
        if port:
            self.edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-port_group-port', port)

    def edit_cred_hpe(self, id, user_name, password, http=False, wsapi_port=None, ssh_port=None):
        self.edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-credentials_group-user', user_name)
        self.edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-password', password)
        if http:
            self.edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-protocol', 'http')
        if wsapi_port:
            self.edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-port', wsapi_port)
        if ssh_port:
            self.edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-ssh_port', ssh_port)

    def edit_cred_microsoft_365(self, id, tenant_id, client_id, client_secret):
        self.edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-tenant_id', tenant_id)
        self.edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-client_id', client_id)
        self.edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-client_secret', client_secret)
        
    def edit_cred_microsoft_azure(self, id, tenant_id, client_id, client_secret, subscription_id):
        self.edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-tenant_id', tenant_id)
        self.edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-client_id', client_id)
        self.edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-client_secret', client_secret)
        self.edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-subscription_id', subscription_id)

    def edit_cred_mqtt(self, id, user_name, password, auth=True, port=None):
        #TODO add TLS settings
        if auth:
            self.edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-active', 'yes')
            self.edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-user', user_name)
            self.edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-password', password)
        if port:
            self.edit_obj_settings(id, 'paessler-mqtt-credentials-connection_mqtt-port_', port)

    def edit_cred_opc_ua(self, id, user_name, password):
        #TODO no credential options
        return
        
    def edit_cred_soffico_orchestra(self, id, user_name, password):
        self.edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-authentication', 'basicAuthentication')
        self.edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-user', user_name)
        self.edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-password', password)

    def edit_cred_redfish(self, id, user_name, password):
        self.edit_obj_settings(id, 'paessler-redfish-redfish_credentials_section-credentials_group-user', user_name)
        self.edit_obj_settings(id, 'paessler-redfish-redfish_credentials_section-credentials_group-password', password)

    def edit_cred_rest_api(self, id, user_name, password, token=False):
        if token:
            self.edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-authentication_method', 'bearer')
            self.edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-custom_bearer', password)
        else:
            self.edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-authentication_method', 'basic_auth')
            self.edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-username', user_name)
            self.edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-password', password)

    def edit_cred_veeam(self, id, user_name, password, port=None):
        self.edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-credentials_group-user', user_name)
        self.edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-credentials_group-password', password)
        if port:
            self.edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-port_group-port', port)

    class Icons(Enum):
        ACER = 'vendors_Acer.png'
        ADTRAN = 'vendors_Adtran.png'
        AMD = 'vendors_AMD.png'
        APC = 'vendors_APC.png'
        APPLE = 'vendors_Apple.png'
        ARUBA = 'vendors_Aruba.png'
        AXIS = 'vendors_Axis.png'
        BARRICUDA = 'vendors_Barricuda.png'
        BROADCOM = 'vendors_Broadcom.png'
        BROCADE = 'vendors_Brocade.png'
        BROTHER = 'vendors_Brother.png'
        BUFFALO = 'vendors_Buffalo.png'
        CANON = 'vendors_Canon.png'
        CHECKPOINT = 'vendors_CheckPoint.png'
        CISCO = 'vendors_Cisco.png'
        CYBERNETICS = 'vendors_Cybernetics.png'
        DELL = 'vendors_DELL.png'
        DLINK = 'vendors_dlink.png'
        EMC = 'vendors_EMC.png'
        EPSON = 'vendors_epson.png'
        FORTINET = 'vendors_Fortinet.png'
        FUJITSU = 'vendors_fujitsu.png'
        HITACHI = 'vendors_Hitachi.png'
        HP = 'vendors_HP.png'
        HPE = 'vendors_HPE.png'
        HUAWEI = 'vendors_Huawei.png'
        IBM = 'vendors_IBM.png'
        INTEL = 'vendors_Intel.png'
        JUNIPER = 'vendors_Juniper.png'
        KEMP = 'vendors_Kemp.png'
        KENTIX = 'vendors_Kentix.png'
        KYOCERA = 'vendors_Kyocera.png'
        LENOVO = 'vendors_Lenovo.png'
        LEXMARK = 'vendors_Lexmark.png'
        LIEBERT = 'vendors_Liebert.png'
        LINKSYS = 'vendors_Linksys.png'
        LOGITECH = 'vendors_Logitech.png'
        MICROTIK = 'vendors_MicroTik.png'
        NETAPP = 'vendors_Netapp.png'
        NIMBLE = 'vendors_Nimble.png'
        NORTEL = 'vendors_Nortel.png'
        OKI = 'vendors_OKI.png'
        ORACLE = 'vendors_Oracle.png'
        PALOALTO = 'vendors_PaloAlto.png'
        PANASONIC = 'vendors_Panasonic.png'
        QNAP = 'vendors_QNAP.png'
        RUCKUS = 'vendors_Ruckus.png'
        RUCKUS2 = 'vendors_Ruckus2.png'
        SAMSUNG = 'vendors_Samsung.png'
        SONOFF = 'vendors_Sonoff.png'
        SONY = 'vendors_Sony.png'
        SOPHOS = 'vendors_Sophos.png'
        SYNOLOGY = 'vendors_synology.png'
        VMWARE = 'vendors_VMware.png'
        WATCHGUARD = 'vendors_Watchguard.png'
        WESTERMO = 'vendors_Westermo.png'
        XEROX = 'vendors_Xerox.png'
        # category fallback icons
        SERVER = 'A_Server_1.png'
        BACKUP = 'A_Server_1.png'
        HARDWARE = 'device.png'
        NETWORK = 'Switch_2.png'
        VIRTUALIZATION = 'C_OS_VMware.png'
        REPLICATION = 'A_Server_1.png'
        STORAGE = 'B_Server_SQL.png'

    def _parse_obj_id(self, url):
        '''Helper function that return the object's id from a URL'''
        decoded_url = urllib.parse.unquote(url)
        try:
            return re.search('(?<=(\?|&)id=)\d+', decoded_url, re.I).group(0)
        except AttributeError:
            logger.error(f'URL does not have matching id: {url}')

    def device_url(self, id):
        '''Helper function builds url for device'''
        return f'{self.url}/device.htm?id={id}'