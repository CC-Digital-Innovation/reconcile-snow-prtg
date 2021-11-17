import configparser
from pathlib import PurePath
from loguru import logger
from pysnow.exceptions import NoResults, MultipleResults

import email_report
import snow_api
from prtg_api import PRTGInstance

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

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
    missing_list = []
    # list of referenced fields: (snow field name, display name, required)
    ref_fields = (
        ('manufacturer', 'Manufacturer', True),
    )
    # list of non-referenced fields
    fields = (
        ('u_category', 'Category (u_category)', True),
        ('u_used_for', 'Used For', True),
        ('u_priority', 'Priority', False),
        ('u_credential_type', 'Credential Type', False),
        ('u_host_name', 'Host Name', True),
        ('ip_address', 'IP Address', False),
        ('u_username', 'Username', False),
        ('u_fs_password', 'FS Password', False),
        ('model_number', 'Model Number', True)
    )
    for device in devices:
        missing = {
            'name': device['name'],
            'link': snow_api.ci_url(device['sys_id']),
            'warnings': [],
            'errors': []
        }
        # check referenced fields
        for field, display_name, required in ref_fields:
            try:
                if not device[field]['display_value']:
                    if required:
                        missing['errors'].append(display_name)
                    else:
                        missing['warnings'].append(display_name)
            except (TypeError, KeyError):
                if required:
                        missing['errors'].append(display_name)
                else:
                    missing['warnings'].append(display_name)
        # check non-referenced fields
        for field, display_name, required in fields:
            if field not in device or not device[field]:
                if required:
                    missing['errors'].append(display_name)
                else:
                    missing['warnings'].append(display_name)
        # remove required name if virtual device
        try:
            if device['u_category'] == 'Virtualization':
                if 'Manufacturer' in missing['errors']:
                    missing['errors'].remove('Manufacturer')
                    missing['warnings'].append('Manufacturer')
                if 'Model Number' in missing['errors']:
                    missing['errors'].remove('Model Number')
                    missing['warnings'].append('Model Number')
        except KeyError:
            pass
        if missing['errors'] or missing['warnings']:
            missing_list.append(missing)
    return missing_list

def init_prtg_from_snow(prtg_instance: PRTGInstance, company_name, site_name, id):
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
    try:
        location = snow_api.get_location(site_name)
    except NoResults:
        logger.error(f'Could not find location with site named {site_name}')
        return f'Could not find location with site named {site_name}'
    except MultipleResults:
        logger.error(f'Found more than one record of site named {site_name}')
        return f'Found more than one record of site named {site_name}'
    # check cmdb fields first
    try:
        missing_list = check_snow_fields(company_name, site_name)
    except ValueError as e:
        return str(e)
    if missing_list:
        if any(len(device['errors']) > 0 for device in missing_list):
            logger.error(f'Missing required fields from cmdb records from {company_name} at {site_name}. Sending report out shortly.')
            email_report.send_missing_list(company_name, site_name, missing_list)
            return f'CMDB records are missing required fields to organize PRTG structure. Check report for more information.'
        else:
            logger.warning(f'Missing optional fields from cmdb records from {company_name} at {site_name}. Continuing PRTG initialization...')
    # Comment when probe device is set. Each Site will have their own probe and as a result, the root group is already made
    root_name = f'[{company["name"]}] {location["name"]}' #TODO use u_site_name when it is consistent (instead of 'name' field)
    root_id = prtg_instance.add_group(root_name, id)
    
    # turn off location inheritance
    prtg_instance.edit_inherit_location(root_id, 0)

    # add location to root group
    try:
        country = snow_api.get_record(location['u_country']['link'])
        prtg_instance.edit_location(root_id, ', '.join((location['street'], location['city'], location['state'], country['result']['name'])))
    except TypeError:
        logger.warning(f'Tried to access record but field u_country is string: {location["u_country"]}')
        logger.warning(f'Adding only street, city, and state/province to location field. Manual adding of country may be required in order for geo map to work: {prtg_instance.device_url(root_id)}')
        prtg_instance.edit_location(root_id, ', '.join((location['street'], location['city'], location['state'])))

    # add service url, i.e. link to ServiceNow configuration item
    prtg_instance.edit_service_url(root_id, snow_api.ci_url(location['sys_id']))

    # track cmdb ci created
    created = []

    # add internal monitoring devices
    cc_inf_id = prtg_instance.add_group('Computacenter Infrastructure', root_id)
    snow_internal_cis = snow_api.get_internal_cis_by_site(company_name, site_name)
    for ci in snow_internal_cis:
        try:
            host_name = ci['u_host_name']
        except KeyError:
            logger.warning('Could not find hostname, falling back to IP address.')
            host_name = ci['ip_address']
        else:
            if not host_name:
                host_name = ci['ip_address']
        if not host_name:
            logger.error(f'Host Name field is empty. Device {ci["name"]} cannot be initialized.')
            continue
        # parse snow field references
        try:
            manuf_ci = snow_api.get_record(ci['manufacturer']['link'])['result']['name']
        except TypeError:
            logger.warning(f'Tried to access record but field manufacturer is string: {ci["manufacturer"]}')
            manuf_ci = ci['manufacturer']
        finally:
            if not manuf_ci:
                if ci['u_category'] != 'Virtualization':
                    logger.error(f'Manufacturer field is empty. Device {ci["name"]} cannot be initialized.')
                    continue
        model_ci = ci['model_number']
        if not model_ci:
            if ci['u_category'] != 'Virtualization':
                logger.error(f'Model Number field is empty. Device {ci["name"]} cannot be initialized.')
                continue
        # construct name, replacing spaces with hyphens
        device_name = ' '.join((host_name.replace(' ', '-'), manuf_ci.replace(' ', '-'), model_ci.replace(' ', '-')))
        device_id = prtg_instance.add_device(device_name, cc_inf_id, ci['ip_address'])
        # edit icon to device
        prtg_instance.edit_icon(device_id, manuf_ci, ci['u_category'])
        # add service url (link to snow record)
        snow_link = snow_api.ci_url(ci['sys_id'])
        prtg_instance.edit_service_url(device_id, snow_link)
        # add tags to device
        prtg_instance.edit_tags(device_id, [ci['u_used_for'], ci['u_category']])
        # add device for reporting
        created.append({
            "prtg": device_name,
            "prtg_link": prtg_instance.device_url(device_id),
            "snow": ci['name'],
            "snow_link": snow_link
        })

    # add customer managed devices
    cust_mng_inf_id = prtg_instance.add_group('Customer Managed Infrastructure', root_id)
    
    # create devices based on stage -> type category -> device
    for stage in snow_api.get_u_used_for_labels():
        # reset stage group
        stage_id = 0
        for category in snow_api.get_u_category_labels():
            snow_cis = snow_api.get_cis_filtered(company['name'], location['name'], category, stage)
            # create stage and category only if there are devices
            if snow_cis:
                if not stage_id:
                    stage_id = prtg_instance.add_group(stage, cust_mng_inf_id)
                category_id = prtg_instance.add_group(category, stage_id)
                for ci in snow_cis:
                    try:
                        host_name = ci['u_host_name']
                    except KeyError:
                        logger.warning('Could not find hostname, falling back to IP address.')
                        host_name = ci['ip_address']
                    else:
                        if not host_name:
                            host_name = ci['ip_address']
                    if not host_name:
                        logger.error(f'Host Name field is empty. Device {ci["name"]} cannot be initialized.')
                        continue
                    # parse snow field references
                    try:
                        manuf_ci = snow_api.get_record(ci['manufacturer']['link'])['result']['name']
                    except TypeError:
                        logger.warning(f'Tried to access record but field manufacturer is string: {ci["manufacturer"]}')
                        manuf_ci = ci['manufacturer']
                    finally:
                        if not manuf_ci:
                            if category != 'Virtualization':
                                logger.error(f'Manufacturer field is empty. Device {ci["name"]} cannot be initialized.')
                                continue
                    model_ci = ci['model_number']
                    if not model_ci:
                        if category != 'Virtualization':
                            logger.error(f'Model Number field is empty. Device {ci["name"]} cannot be initialized.')
                            continue
                    # construct name, replacing spaces with hyphens
                    device_name = ' '.join((host_name.replace(' ', '-'), manuf_ci.replace(' ', '-'), model_ci.replace(' ', '-')))
                    device_id = prtg_instance.add_device(device_name, category_id, ci['ip_address'])
                    # edit icon to device
                    prtg_instance.edit_icon(device_id, manuf_ci, category)
                    # add service url (link to snow record)
                    snow_link = snow_api.ci_url(ci['sys_id'])
                    prtg_instance.edit_service_url(device_id, snow_link)
                    
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

                    # add tags to device
                    prtg_instance.edit_tags(device_id, [stage, category])

                    # add device for reporting
                    created.append({
                        "prtg": device_name,
                        "prtg_link": prtg_instance.device_url(device_id),
                        "snow": ci['name'],
                        "snow_link": snow_link
                    })
    # email report
    logger.info('Successfully deployed PRTG devices from SNOW. Sending email report...')
    email_report.send_success_init_prtg(company_name, site_name, created, missing_list)