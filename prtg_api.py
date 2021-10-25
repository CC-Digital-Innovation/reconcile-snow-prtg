import configparser
import re
import urllib.parse
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import PurePath

import requests
from loguru import logger

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

def get_sensortree():
    url = config['prtg']['base_url'] + '/api/table.xml'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'content': 'sensortree'
    }
    response = requests.get(url, params)
    response.raise_for_status
    return response.text

def get_probe_id(company_name, site_name):
    name = f'[{company_name}] {site_name}'
    tree = ET.fromstring(get_sensortree())
    groups = []
    groups.extend(tree.iter('group'))
    groups.extend(tree.iter('probenode'))
    for element in groups:
        if element.find('name').text == name:
            return element.get('id')

def get_obj_status(id, property):
    # includes some property-like properties like parent ID
    url = config['prtg']['base_url'] + '/api/getobjectstatus.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': id,
        'name': property,
        'show': 'nohtmlencode'
    }
    response = requests.get(url, params)
    response.raise_for_status
    tree = ET.fromstring(response.text)
    try:
        result = tree.find('result').text
        return result
    except AttributeError:
        logger.error('Cannot find element result.')

def get_obj_property(id, property):
    url = config['prtg']['base_url'] + '/api/getobjectproperty.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': id,
        'name': property,
        'show': 'nohtmlencode'
    }
    response = requests.get(url, params)
    response.raise_for_status
    tree = ET.fromstring(response.content)
    try:
        result = tree.find('result').text
        return result
    except AttributeError:
        logger.error('Cannot find element result.')

def get_devices(group_id=None):
    '''Returns a list of all devices. If a group id is given,
    return a list of all devices only from that group.'''
    if group_id:
        logger.info(f'Getting all devices from group with id {group_id}')
    else:
        logger.info('Getting all devices')
    url = config['prtg']['base_url'] + '/api/table.json'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'content': 'devices',
        'columns': 'objid,name,active,device,group,priority,host,tags,location,parentid',
        'id': group_id
    }
    response = requests.get(url, params)
    response.raise_for_status
    return response.json()['devices']

def add_group(name, group_id, template=config['prtg']['template_group']):
    '''Adds a new group.'''
    logger.info(f'Adding group {name} to group with id {group_id}')
    url = config['prtg']['base_url'] + '/api/duplicateobject.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': template,
        'name': name,
        'targetid': group_id
    }
    response = requests.get(url, params)
    response.raise_for_status
    id = _parse_obj_id(response.url)
    # an error will capture the template's id
    if str(id) != str(template):
        return id

def add_device(name, group_id, host, template=config['prtg']['template_device']):
    '''Adds a new device.'''
    logger.info(f'Adding device {name} to group with id {group_id}')
    url = config['prtg']['base_url'] + '/api/duplicateobject.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': template,
        'name': name,
        'host': host,
        'targetid': group_id
    }
    response = requests.get(url, params)
    response.raise_for_status
    id = _parse_obj_id(response.url)
    # an error will capture the template's id
    if str(id) != str(template):
        return id

def add_sensor(name, device_id, template=config['prtg']['template_sensor']):
    '''Adds a new sensor'''
    logger.info(f'Adding sensor {name} to device with id {device_id}')
    url = config['prtg']['base_url'] + '/api/duplicateobject.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': template,
        'name': name,
        'targetid': device_id
    }
    response = requests.get(url, params)
    response.raise_for_status
    id = _parse_obj_id(response.url)
    # an error will capture the template's id
    if str(id) != str(template):
        return id

def edit_obj_settings(id, name, value):
    '''Base api to change all object settings'''
    url = config['prtg']['base_url'] + '/api/setobjectproperty.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': id,
        'name': name,
        'value': value
    }
    response = requests.get(url, params)
    response.raise_for_status

def edit_priority(id, value):
    '''Set object priority.'''
    if value < 1 or value > 5:
        raise ValueError('Priorty can only set between 1 - 5.')
    url = config['prtg']['base_url'] + '/api/setpriority.htm'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': id,
        'prio': value
    }
    response = requests.get(url, params)
    response.raise_for_status

def edit_icon(id, vendor, category=None):
    try:
        vendors = vendor.split('/')
        icon = Icons[vendors[0].upper()]
        edit_obj_settings(id, 'deviceicon', icon.value)
    except KeyError:
        logger.warning('Vendor not recognized, using category as fallback.')
        edit_obj_settings(id, 'deviceicon', category)

def edit_location(id, location):
    edit_obj_settings(id, 'location', location)

def edit_service_url(id, url):
    edit_obj_settings(id, 'serviceurl', url)

def edit_tags(id, tags):
    '''OVERWRITES the tags of an object'''
    # api accepts each space-separated word as a tag
    combined_tags = ' '.join(tags)
    edit_obj_settings(id, 'tags', combined_tags)

def edit_obj_inherit(id, inherit_type, value):
    '''Base api to switch off/on inheritance settings.
    Value accepts int 0 (off) or 1 (on).'''
    if value != 0 and value != 1:
        raise ValueError('Value can only be 0 or 1')
    url = config['prtg']['base_url'] + '/editsettings'
    params = {
        'username': config['prtg']['username'],
        'passhash': config['prtg']['passhash'],
        'id': id,
        inherit_type: value
    }
    response = requests.get(url, params)
    response.raise_for_status
    return _parse_obj_id(response.url)

def edit_inherit_location(id, value):
    return edit_obj_inherit(id, 'locationgroup', value)

def edit_cred_windows(id, domain_name, user_name, password):
    # domain_name can also be computer name if using local user account
    edit_obj_settings(id, 'windowslogindomain', domain_name)
    edit_obj_settings(id, 'windowsloginusername', user_name)
    edit_obj_settings(id, 'windowsloginpassword', password)

def edit_cred_linux(id, user_name, password, private_key=False, wbem_http=False, wbem_port=None, ssh_port=None):
    edit_obj_settings(id, 'linuxloginusername', user_name)
    edit_obj_settings(id, 'linuxloginpassword', password)
    if private_key:
        edit_obj_settings(id, 'linuxloginmode', 1)
    if wbem_http:
        edit_obj_settings(id, 'wbemprotocol', 'http')
    if wbem_port:
        edit_obj_settings(id, 'wbemportmode', 1)
        edit_obj_settings(id, 'wbemport', wbem_port)
    if ssh_port:
        edit_obj_settings(id, 'sshport', ssh_port)

def edit_cred_vmware(id, user_name, password, http=False):
    edit_obj_settings(id, 'esxuser', user_name)
    edit_obj_settings(id, 'esxpassword', password)
    if http:
        edit_obj_settings(id, 'esxprotocol', 1)

def edit_cred_snmp(id, version, community_str, port):
    # acceptable version values are 'V1' | 'V2' | 'V3'
    edit_obj_settings(id, 'snmpversion', version)
    edit_obj_settings(id, 'snmpcommv2', community_str)
    edit_obj_settings(id, 'snmpport', port)

def edit_cred_dbms(id, user_name, password, port=None, window_auth=False):
    if port:
        edit_obj_settings(id, 'usedbcustomport', 1)
        edit_obj_settings(id, 'dbport', port)
    if not window_auth:
        edit_obj_settings(id, 'dbauth', 1)
        edit_obj_settings(id, 'dbuser', user_name)
        edit_obj_settings(id, 'dbpassword', password)

def edit_cred_aws(id, access_key, secret_key):
    edit_obj_settings(id, 'awsak', access_key)
    edit_obj_settings(id, 'awssk', secret_key)
    
def edit_cred_dell_emc(id, user_name, password, port=None):
    edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-user', user_name)
    edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-password', password)
    if port:
        edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-port_group-port', port)

def edit_cred_hpe(id, user_name, password, http=False, wsapi_port=None, ssh_port=None):
    edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-credentials_group-user', user_name)
    edit_obj_settings(id, 'paessler-dellemc-dellemc_credentials_section-credentials_group-password', password)
    if http:
        edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-protocol', 'http')
    if wsapi_port:
        edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-port', wsapi_port)
    if ssh_port:
        edit_obj_settings(id, 'paessler-hpe3par-hpe3par_credentials_section-connection_group-ssh_port', ssh_port)

def edit_cred_microsoft_365(id, tenant_id, client_id, client_secret):
    edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-tenant_id', tenant_id)
    edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-client_id', client_id)
    edit_obj_settings(id, 'paessler-microsoft365-azure_ad_credentials_section-credentials_group-client_secret', client_secret)
    
def edit_cred_microsoft_azure(id, tenant_id, client_id, client_secret, subscription_id):
    edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-tenant_id', tenant_id)
    edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-client_id', client_id)
    edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-client_secret', client_secret)
    edit_obj_settings(id, 'paessler-microsoftazure-azure_credentials_section-credentials_group-subscription_id', subscription_id)

def edit_cred_mqtt(id, user_name, password, auth=True, port=None):
    #TODO add TLS settings
    if auth:
        edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-active', 'yes')
        edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-user', user_name)
        edit_obj_settings(id, 'paessler-mqtt-credentials-user_credentials-password', password)
    if port:
        edit_obj_settings(id, 'paessler-mqtt-credentials-connection_mqtt-port_', port)

def edit_cred_opc_ua(id, user_name, password):
    #TODO no credential options
    return
    
def edit_cred_soffico_orchestra(id, user_name, password):
    edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-authentication', 'basicAuthentication')
    edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-user', user_name)
    edit_obj_settings(id, 'paessler-orchestra-credentials_orchestra_section-credentials_orchestra_group-password', password)

def edit_cred_redfish(id, user_name, password):
    edit_obj_settings(id, 'paessler-redfish-redfish_credentials_section-credentials_group-user', user_name)
    edit_obj_settings(id, 'paessler-redfish-redfish_credentials_section-credentials_group-password', password)

def edit_cred_rest_api(id, user_name, password, token=False):
    if token:
        edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-authentication_method', 'bearer')
        edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-custom_bearer', password)
    else:
        edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-authentication_method', 'basic_auth')
        edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-username', user_name)
        edit_obj_settings(id, 'paessler-rest-authentication_section-authentication_group-password', password)

def edit_cred_veeam(id, user_name, password, port=None):
    edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-credentials_group-user', user_name)
    edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-credentials_group-password', password)
    if port:
        edit_obj_settings(id, 'paessler-veeam-veeam_enterprise_manager_settings-port_group-port', port)

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
    SERVER = 'A_Server_1'
    BACKUP = 'A_Server_1'
    NETWORK = 'Switch_2.png'
    VIRTUALIZATION = 'C_OS_VMware'
    REPLICATION = 'A_Server_1'
    STORAGE = 'B_Server_SQL.png'

def _parse_obj_id(url):
    '''Helper function that return the object's id from a URL'''
    decoded_url = urllib.parse.unquote(url)
    try:
        return re.search('(?<=(\?|&)id=)\d+', decoded_url, re.I).group(0)
    except AttributeError:
        logger.error(f'URL does not have matching id: {url}')

def device_url(id):
    '''Helper function builds url for device'''
    return f'{config["prtg"]["base_url"]}/device.htm?id={id}'