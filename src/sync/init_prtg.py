import time

from loguru import logger
from prtg import ApiClient
from prtg.icon import Icon
from pysnow.exceptions import MultipleResults, NoResults

import report
from snow import snow_api


class SnowField:
    def __init__(self, name: str, display_name: str, reference: bool=False, fallback=None, required: bool=True):
        self.name = name
        self.display_name = display_name
        self.reference = reference
        self.fallback = fallback
        self.required = required

def check_snow_fields(company_name, site_name):
    '''Check cmdb fields and warns if any are missing
    
    Returns
    -------
    list
        Returns a list of dicts containing details about the device and its missing fields

    Raises
    ------
    ValueError
        If no devices can be found on ServiceNow
    '''
    devices = snow_api.get_customer_cis_by_site(company_name, site_name)
    if not devices:
        raise ValueError(f'No prtg managed devices found for {company_name} at {site_name}')
    # list of devices with missing field(s)
    missing_list = []
    # SNOW fields to be checked
    fields = []
    fields.append(SnowField('name', 'Name'))
    fields.append(SnowField('u_category', 'Category', required=False))
    fields.append(SnowField('u_used_for', 'Used For'))
    fields.append(SnowField('ip_address', 'IP Address'))
    fields.append(SnowField('manufacturer', 'Manufacturer', reference=True))
    fields.append(SnowField('model_number', 'Model Number'))
    # TODO uncomment when SNOW field is implemented
    # fields.append(SnowField('u_credential_type', 'Credential Type', required=False))
    # fields.append(SnowField('u_username', 'Username', required=False))
    # fields.append(SnowField('u_fs_password', 'FS Password', required=False))
    # fields.append(SnowField('u_priority', 'Priority', required=False))

    for device in devices:
        missing = {
            'name': device['name'],
            'link': snow_api.ci_url(device['sys_id']),
            'warnings': [],
            'errors': []
        }
        i = 0
        temp_fields = fields.copy()
        while i < len(temp_fields):
            # check referenced fields
            if temp_fields[i].reference:
                try:
                    if not device[temp_fields[i].name]['display_value']:
                        if temp_fields[i].fallback:
                            temp_fields.append(temp_fields[i].fallback)
                            i += 1
                            continue
                        if temp_fields[i].required:
                            missing['errors'].append(temp_fields[i].display_name)
                        else:
                            missing['warnings'].append(temp_fields[i].display_name)
                except (TypeError, KeyError):
                    if temp_fields[i].fallback:
                        temp_fields.append(temp_fields[i].fallback)
                        i += 1
                        continue
                    if temp_fields[i].required:
                            missing['errors'].append(temp_fields[i].display_name)
                    else:
                        missing['warnings'].append(temp_fields[i].display_name)
            # check non-referenced fields
            else:
                if temp_fields[i].name not in device or not device[temp_fields[i].name]:
                    if temp_fields[i].fallback:
                        temp_fields.append(temp_fields[i].fallback)
                        i += 1
                        continue
                    if temp_fields[i].required:
                        missing['errors'].append(temp_fields[i].display_name)
                    else:
                        missing['warnings'].append(temp_fields[i].display_name)
            i += 1

        if missing['errors'] or missing['warnings']:
            missing_list.append(missing)
    return missing_list

def init_prtg_from_snow(prtg_instance: ApiClient, company_name, site_name, probe_id, resume=False, site_probe=False):
    '''Initializes PRTG devices to proper structure from ServiceNow cmdb configuration items.
    Currently sends an email reports for unsuccessful/successful initialization.

    Returns
    -------
    str
        Response to be forwarded to fastapi endpoint responses
    '''
    try:
        company = snow_api.get_company(company_name)
    except NoResults:
        logger.error(f'Could not find company {company_name}')
        return f'Could not find company {company_name}'
    except MultipleResults:
        logger.error(f'Found more than one record of company {company_name}')
        return f'Found more than one record of company {company_name}'
    company['name'] = company['name'].strip()
    try:
        location = snow_api.get_location(site_name)
    except NoResults:
        logger.error(f'Could not find location with site named {site_name}')
        return f'Could not find location with site named {site_name}'
    except MultipleResults:
        logger.error(f'Found more than one record of site named {site_name}')
        return f'Found more than one record of site named {site_name}'
    location['name'] = location['name'].strip()
    # check cmdb fields first
    try:
        missing_list = check_snow_fields(company_name, site_name)
    except ValueError as e:
        return str(e)
    if missing_list:
        if any(len(device['errors']) > 0 for device in missing_list):
            logger.error(f'Missing required fields from cmdb records from {company_name} at {site_name}. Sending report out shortly.')
            report.send_missing_list(company_name, site_name, missing_list)
            return f'CMDB records are missing required fields to organize PRTG structure. Check report for more information.'
        else:
            logger.warning(f'Missing optional fields from cmdb records from {company_name} at {site_name}. Continuing PRTG initialization...')
    
    # get probe name for proper logging
    probe_name = prtg_instance.get_probe(probe_id)['name']

    # whether probe is site specific or use groups for sites
    if site_probe:
        root_id = probe_id
    else:
        root_name = f'[{probe_name}] {location["name"]}' #TODO use u_site_name when it is consistent (instead of 'name' field)
        root = prtg_instance.add_group(root_name, probe_id)
        time.sleep(5)
        root_id = root['objid']
        prtg_instance.resume_object(root_id)
    
        # # turn off location inheritance
        prtg_instance.set_inherit_location_off(root_id)

    # add location to root group
    try:
        country = snow_api.get_record(location['u_country']['link'])
        prtg_instance.set_location(root_id, ', '.join((location['street'].replace('\r\n', ' '), location['city'].replace('\r\n', ' '), location['state'].replace('\r\n', ' '), country['result']['name'].replace('\r\n', ' '))))
    except TypeError:
        logger.warning(f'Tried to access record but field u_country is string: {location["u_country"]}')
        logger.warning(f'Adding only street, city, and state/province to location field. Manual adding of country may be required in order for geo map to work: {prtg_instance.device_url(root_id)}')
        prtg_instance.set_location(root_id, ', '.join((location['street'].replace('\r\n', ' '), location['city'].replace('\r\n', ' '), location['state'].replace('\r\n', ' '))))

    # add service url, i.e. link to ServiceNow configuration item
    prtg_instance.set_service_url(root_id, snow_api.ci_url(location['sys_id']))

    # track cmdb ci created
    created = []

    # add internal monitoring devices
    snow_internal_cis = snow_api.get_internal_cis_by_site(company_name, site_name)
    if snow_internal_cis:
        cc_inf = prtg_instance.add_group(f'[{probe_name}] CC Infrastructure', root_id)
        time.sleep(5)
        cc_inf_id = cc_inf['objid']
        prtg_instance.resume_object(cc_inf_id)
    for ci in snow_internal_cis:
        # parse snow fields
        access = ci['ip_address']
        if not access:
            logger.error(f'IP address field cannot be found. Device {ci["name"]} cannot be initialized.')
            continue
        try:
            manuf_ci = snow_api.get_record(ci['manufacturer']['link'])['result']['name']
        except TypeError:
            logger.warning(f'Tried to access record but field manufacturer is string: {ci["manufacturer"]}')
            manuf_ci = ci['manufacturer']
        except KeyError as e:
            logger.debug(snow_api.get_record(ci['manufacturer']['link']))
            manuf_ci = ''
        device_name = '{} {} ({})'.format(manuf_ci, ci['model_number'], access)
        device = prtg_instance.add_device(device_name, access, cc_inf_id)
        time.sleep(5)
        device_id = device['objid']
        snow_api.update_prtg_id(ci['sys_id'], device_id)
        if resume:
            prtg_instance.resume_object(device_id)
        # edit icon to device
        try:
            prtg_instance.set_icon(device_id, Icon[manuf_ci.upper()])
        except KeyError:
            #TODO implement fallback mapping for general icons
            pass
        # add service url (link to snow record)
        snow_link = snow_api.ci_url(ci['sys_id'])
        prtg_instance.set_service_url(device_id, snow_link)
        # add tags to device
        prtg_instance.set_tags(device_id, [ci['u_used_for'], ci['u_category'].replace(' ', '-')])
        # add device for reporting
        created.append({
            "prtg": device_name,
            "prtg_link": prtg_instance.device_url(device_id),
            "snow": ci['name'],
            "snow_link": snow_link
        })

    # add customer managed devices
    cust_mng_inf = prtg_instance.add_group(f'[{probe_name}] Customer Managed Infrastructure', root_id)
    time.sleep(5)
    cust_mng_inf_id = cust_mng_inf['objid']
    prtg_instance.resume_object(cust_mng_inf_id)
    
    # create devices based on stage -> type category -> device
    cis = snow_api.get_customer_cis_by_site(company_name, site_name)
    ordered_ci = {}
    for stage in snow_api.get_u_used_for_labels():
        ordered_ci[stage] = {}
    for ci in cis:
        try:
            ordered_ci[ci['u_used_for']][ci['u_category']].append(ci)
        except KeyError:
            ordered_ci[ci['u_used_for']][ci['u_category']] = [ci]
    for stage, class_list in ordered_ci.items():
        if class_list:
            stage_obj = prtg_instance.add_group(f'[{probe_name}] {stage}', cust_mng_inf_id)
            time.sleep(5)
            stage_id = stage_obj['objid']
            prtg_instance.set_tags(stage_id, [stage])
            prtg_instance.resume_object(stage_id)
            for class_name, devices in class_list.items():
                class_obj = prtg_instance.add_group(f'[{probe_name}] {class_name}', stage_id)
                time.sleep(5)
                class_id = class_obj['objid']
                prtg_instance.set_tags(class_id, [class_name.replace(' ', '-')])
                prtg_instance.resume_object(class_id)
                for ci in sorted(devices, key=lambda x: x['name']):
                    try:
                        access = ci['ip_address']
                        if not access:
                            logger.error(f'IP address field cannot be found. Device {ci["name"]} cannot be initialized.')
                            continue
                        try:
                            manuf_ci = snow_api.get_record(ci['manufacturer']['link'])['result']['name']
                        except TypeError:
                            logger.warning(f'Tried to access record but field manufacturer is string: {ci["manufacturer"]}')
                            manuf_ci = ci['manufacturer']
                        except KeyError as e:
                            logger.debug(snow_api.get_record(ci['manufacturer']['link']))
                            manuf_ci = ''
                        device_name = '{} {} ({})'.format(manuf_ci, ci['model_number'], access)
                        logger.debug(f'Adding device {ci["name"]}')
                        device_obj = prtg_instance.add_device(device_name, access, class_id)
                        time.sleep(5)
                        device_id = device_obj['objid']
                        snow_api.update_prtg_id(ci['sys_id'], device_id)
                        if resume:
                            prtg_instance.resume_object(device_id)
                        # edit icon to device
                        try:
                            prtg_instance.set_icon(device_id, Icon[manuf_ci.upper()])
                        except KeyError:
                            #TODO implement fallback mapping for general icons
                            pass
                        # add service url (link to snow record)
                        snow_link = snow_api.ci_url(ci['sys_id'])
                        prtg_instance.set_service_url(device_id, snow_link)
                        
                        # TODO uncomment when ServiceNow fields are added
                        # if ci['u_credential_type']:
                        #     if ci['u_credential_type'].lower() == 'windows':
                        #         prtg_instance.edit_cred_windows(device_id, ci['dns_domain'], ci['u_username'], snow_api.decrypt_password(device_id))
                        #     elif ci['u_credential_type'].lower() == 'linux':
                        #         private_key = ci['u_private_key'].lower() == 'true'
                        #         wbem_http = ci['u_wbem_http'].lower() == 'true'
                        #         wbem_port = ci['u_wbem_port'] if ci['u_wbem_port'] else None
                        #         ssh_port = ci['u_ssh_port'] if ci['u_ssh_port'] else None
                        #         prtg_instance.edit_cred_linux(device_id, snow_api.decrypt_password(device_id), private_key, wbem_http, wbem_port, ssh_port)
                        #     elif ci['u_credential_type'].lower() == 'vmware':
                        #         http = ci['u_http'].lower() == 'true'
                        #         prtg_instance.edit_cred_vmware(device_id, ci['u_username'], snow_api.decrypt_password(device_id), http)
                        #     elif ci['u_credential_type'].lower() == 'snmp':
                        #         prtg_instance.edit_cred_snmp(device_id, ci['u_snmp_version'], ci['u_community_string'], ci['u_port'])
                        #     elif ci['u_credential_type'].lower() == 'dbms':
                        #         port = ci['u_port'] if ci['u_port'] else None
                        #         prtg_instance.edit_cred_dbms(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)
                        #     elif ci['u_credential_type'].lower() == 'aws':
                        #         prtg_instance.edit_cred_aws(device_id, ci['u_access_key'], ci['u_secret_key'])
                        #     elif ci['u_credential_type'].lower() == 'dell_emc':
                        #         port = ci['u_port'] if ci['u_port'] else None
                        #         prtg_instance.edit_cred_dell_emc(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)
                        #     elif ci['u_credential_type'].lower() == 'hpe_3par':
                        #         http = ci['u_http'].lower() == 'true'
                        #         wsapi_port = ci['u_wsapi_port'] if ci['u_wsapi_port'] else None
                        #         ssh_port = ci['u_ssh_port'] if ci['u_ssh_port'] else None
                        #         prtg_instance.edit_cred_hpe(device_id, ci['u_username'], snow_api.decrypt_password(device_id), http, wsapi_port, ssh_port)
                        #     elif ci['u_credential_type'].lower() == 'microsoft_365':
                        #         prtg_instance.edit_cred_microsoft_365(device_id, ci['u_tenant_id'], ci['u_client_id'], ci['u_client_secret'])
                        #     elif ci['u_credential_type'].lower() == 'microsoft_azure':
                        #         prtg_instance.edit_cred_microsoft_azure(device_id, ci['u_tenant_id'], ci['u_client_id'], ci['u_client_secret'], ci['u_subscription_id'])
                        #     elif ci['u_credential_type'].lower() == 'mqtt':
                        #         port = ci['u_port'] if ci['u_port'] else None
                        #         prtg_instance.edit_cred_mqtt(device_id, ci['u_username'], snow_api.decrypt_password(device_id), True, port)
                        #     elif ci['u_credential_type'].lower() == 'opc ua':
                        #         prtg_instance.edit_cred_opc_ua(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                        #     elif ci['u_credential_type'].lower() == 'soffico orchestra':
                        #         prtg_instance.edit_cred_soffico_orchestra(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                        #     elif ci['u_credential_type'].lower() == 'redfish':
                        #         prtg_instance.edit_cred_redfish(device_id, ci['u_username'], snow_api.decrypt_password(device_id))
                        #     elif ci['u_credential_type'].lower() == 'rest api':
                        #         token = ci['u_token'] == 'true'
                        #         prtg_instance.edit_cred_rest_api(device_id, ci['u_username'], snow_api.decrypt_password(device_id), token)
                        #     elif ci['u_credential_type'].lower() == 'veeam':
                        #         port = ci['u_port'] if ci['u_port'] else None
                        #         prtg_instance.edit_cred_veeam(device_id, ci['u_username'], snow_api.decrypt_password(device_id), port)

                        #TODO uncomment when ServiceNow fields are added
                        # prtg_instance.edit_priority(device_id, ci['priority'])

                        # add device for reporting
                        created.append({
                            "prtg": device_name,
                            "prtg_link": prtg_instance.device_url(device_id),
                            "snow": ci['name'],
                            "snow_link": snow_link
                        })
                        time.sleep(10)
                    except Exception as e:
                        logger.error(f'{str(e)}. Cannot handle issue for device {ci["name"]}, trying with next device')

    # email report
    logger.info('Successfully deployed PRTG devices from SNOW. Sending email report...')
    report.send_success_init_prtg(company_name, site_name, created, missing_list)
