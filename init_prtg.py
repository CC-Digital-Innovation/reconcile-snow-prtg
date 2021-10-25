import configparser
from pathlib import PurePath
from loguru import logger
from pysnow.exceptions import NoResults, MultipleResults

import prtg_api
import snow_api

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

def check_snow_fields(company_name, location):
    '''Check cmdb fields and warns if any are missing'''
    #TODO implement
    # optional: street, city, state/province, country
    # required: site name, manufacturer, model_id, host_name, ip_address?, used_for, priority

def init_prtg_from_snow(company_name, site_name, id):
    try:
        company = snow_api.get_company(company_name)
    except NoResults:
        logger.error(f'Could not find company {company_name}')
        return
    except MultipleResults:
        logger.error(f'Found more than one record of company {company_name}')
        return
    try:
        location = snow_api.get_location(site_name)
    except NoResults:
        logger.error(f'Could not find location with site named {site_name}')
        return
    except MultipleResults:
        logger.error(f'Found more than one record of site named {site_name}')
        return
    # Comment when probe device is set. Each Site will have their own probe and as a result, the root group is already made
    root_name = f'[{company["name"]}] {location["name"]}' #TODO use u_site_name when it is consistent (instead of 'name' field)
    root_id = prtg_api.add_group(root_name, id)
    
    # turn off location inheritance
    prtg_api.edit_inherit_location(root_id, 0)

    # add location to root group
    try:
        country = snow_api.get_record(location['u_country']['link'])
        prtg_api.edit_location(root_id, ', '.join((location['street'], location['city'], location['state'], country['result']['name'])))
    except TypeError:
        logger.warning(f'Tried to access record but field u_country is string: {location["u_country"]}')
        logger.warning(f'Adding only street, city, and state/province to location field. Manual adding of country may be required in order for geo map to work: {prtg_api.device_url(root_id)}')
        prtg_api.edit_location(root_id, ', '.join((location['street'], location['city'], location['state'])))

    # add service url, i.e. link to ServiceNow configuration item
    prtg_api.edit_service_url(root_id, snow_api.ci_url(location['sys_id']))

    prtg_api.add_group('Computacenter Infrastructure', root_id)
    cust_mng_inf_id = prtg_api.add_group('Customer Managed Infrastructure', root_id)

    # create devices based on stage -> type category -> device
    for stage in snow_api.get_u_used_for_labels():
        # reset stage group
        stage_id = 0
        for category in snow_api.get_u_category_labels():
            snow_cis = snow_api.get_cis_filtered(company['name'], location['name'], category, stage)
            # create stage and category only if there are devices
            if snow_cis:
                if not stage_id:
                    stage_id = prtg_api.add_group(stage, cust_mng_inf_id)
                category_id = prtg_api.add_group(category, stage_id)
                for ci in snow_cis:
                    #TODO temporary solution: check only for ip address included devices
                    #     future solution: check for prtg managed devices once field is added
                    if not ci['ip_address']:
                        continue
                    host_name = ci['u_host_name']
                    # ip address as fallback in no hostname
                    if not host_name:
                        try:
                            host_name = ci['host_name']
                        except KeyError:
                            pass
                        if not host_name:
                            host_name = ci['ip_address']
                    # parse snow field references
                    try:
                        vendor_ci = snow_api.get_record(ci['vendor']['link'])['result']['name']
                    except TypeError:
                        logger.warning(f'Tried to access record but field vendor is string: {ci["vendor"]}')
                        vendor_ci = ci['vendor']
                    try:
                        manuf_ci = snow_api.get_record(ci['manufacturer']['link'])['result']['name']
                    except TypeError:
                        logger.warning(f'Tried to access record but field manufacturer is string: {ci["manufacturer"]}')
                        manuf_ci = ci['manufacturer']
                    try:
                        model_ci = snow_api.get_record(ci['model_id']['link'])['result']['display_name']
                    except TypeError:
                        logger.warning(f'Tried to access record but field model_id is string: {ci["model_id"]}')
                        model_ci = ci['model_id']
                    # edit icon to device
                    device_id = prtg_api.add_device(' '.join((host_name, manuf_ci, model_ci)), category_id, ci['ip_address'])
                    if vendor_ci:
                        prtg_api.edit_icon(device_id, vendor_ci)
                    else:
                        prtg_api.edit_icon(device_id, manuf_ci)
                    # add service url (link to snow record)
                    prtg_api.edit_service_url(device_id, snow_api.ci_url(ci['sys_id']))
                    
                    # TODO uncomment when ServiceNow fields are added
                    # if ci['u_credential_type']:
                    #     if ci['u_credential_type'].lower() == 'windows':
                    #         prtg_api.edit_cred_windows(device_id, ci['dns_domain'], ci['u_username'], snow_api.decrypt_password(device_id))
                    #     elif ci['u_credential_type'].lower() == 'linux':
                    #         private_key = ci['u_private_key'].lower() == 'true'
                    #         wbem_http = ci['u_wbem_http'].lower() == 'true'
                    #         wbem_port = ci['u_wbem_port'] if ci['u_wbem_port'] else None
                    #         ssh_port = ci['u_ssh_port'] if ci['u_ssh_port'] else None
                    #         prtg_api.edit_cred_linux(device_id, snow_api.decrypt_password(device_id), private_key, wbem_http, wbem_port, ssh_port)
                    #     elif ci['u_credential_type'].lower() == 'vmware':
                    #         http = ci['u_http'].lower() == 'true'
                    #         prtg_api.edit_cred_vmware(device_id, ci['u_username'], snow_api.decrypt_password(device_id), http)
                    #     elif ci['u_credential_type'].lower() == 'snmp':
                    #         prtg_api.edit_cred_snmp(device_id, ci['u_snmp_version'], ci['u_community_string'], ci['u_port'])
                    #     elif ci['u_credential_type'].lower() == 'dbms':
                    #         port = ci['u_port'] if ci['u_port'] else None
                    #         prtg_api.edit_cred_dbms(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)
                    #     elif ci['u_credential_type'].lower() == 'aws':
                    #         prtg_api.edit_cred_aws(device_id, ci['u_access_key'], ci['u_secret_key'])
                    #     elif ci['u_credential_type'].lower() == 'dell_emc':
                    #         port = ci['u_port'] if ci['u_port'] else None
                    #         prtg_api.edit_cred_dell_emc(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)
                    #     elif ci['u_credential_type'].lower() == 'hpe_3par':
                    #         http = ci['u_http'].lower() == 'true'
                    #         wsapi_port = ci['u_wsapi_port'] if ci['u_wsapi_port'] else None
                    #         ssh_port = ci['u_ssh_port'] if ci['u_ssh_port'] else None
                    #         prtg_api.edit_cred_hpe(device_id, ci['u_username'], snow_api.decrypt_password(device_id), http, wsapi_port, ssh_port)
                    #     elif ci['u_credential_type'].lower() == 'microsoft_365':
                    #         prtg_api.edit_cred_microsoft_365(device_id, ci['u_tenant_id'], ci['u_client_id'], ci['u_client_secret'])
                    #     elif ci['u_credential_type'].lower() == 'microsoft_azure':
                    #         prtg_api.edit_cred_microsoft_azure(device_id, ci['u_tenant_id'], ci['u_client_id'], ci['u_client_secret'], ci['u_subscription_id'])
                    #     elif ci['u_credential_type'].lower() == 'mqtt':
                    #         port = ci['u_port'] if ci['u_port'] else None
                    #         prtg_api.edit_cred_mqtt(device_id, ci['u_username'], snow_api.decrypt_password(device_id), True, port)
                    #     elif ci['u_credential_type'].lower() == 'opc ua':
                    #         prtg_api.edit_cred_opc_ua(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                    #     elif ci['u_credential_type'].lower() == 'soffico orchestra':
                    #         prtg_api.edit_cred_soffico_orchestra(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                    #     elif ci['u_credential_type'].lower() == 'redfish':
                    #         prtg_api.edit_cred_redfish(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                    #     elif ci['u_credential_type'].lower() == 'rest api':
                    #         token = ci['u_token'] == 'true'
                    #         prtg_api.edit_cred_rest_api(device_id, ci['u_username'], snow_api.decrypt_password(device_id), token)
                    #     elif ci['u_credential_type'].lower() == 'veeam':
                    #         port = ci['u_port'] if ci['u_port'] else None
                    #         prtg_api.edit_cred_veeam(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)

                    #TODO uncomment when ServiceNow fields are added
                    # prtg_api.edit_priority(device_id, ci['priority'])

                    # add tags to device
                    prtg_api.edit_tags(device_id, [stage, category])