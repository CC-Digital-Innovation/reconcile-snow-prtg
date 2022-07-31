import xml.etree.ElementTree as ET

import email_report
import snow_api
from loguru import logger

from prtg import init_prtg
from prtg.exception import ProbeNotFound
from prtg.prtg_api import PRTGInstance

def update_company(prtg_instance: PRTGInstance, company_name, site_name, resume):
    # get snow devices
    snow_cis = snow_api.get_cis_by_site(company_name, site_name)
    # get prtg devices
    group_id = prtg_instance.get_probe_id(company_name, site_name)
    if group_id:
        prtg_devices = prtg_instance.get_devices(group_id)
    else:
        prtg_devices = None

    # not prtg managed
    if not snow_cis and not prtg_devices:
        return

    # prtg managed devices exist but probe could not be found
    if snow_cis and prtg_devices is None:
        raise ProbeNotFound(f'Could not find PRTG probe of company {company_name} at {site_name}')
    
    # check cmdb fields first
    try:
        missing_list = init_prtg.check_snow_fields(company_name, site_name)
    except ValueError as e:
        return str(e)
    if missing_list:
        if any(len(device['errors']) > 0 for device in missing_list):
            logger.error(f'Missing required fields from cmdb records from {company_name} at {site_name}. Sending report out shortly.')
            email_report.send_missing_list(company_name, site_name, missing_list)
            return f'CMDB records are missing required fields to organize PRTG structure. Check report for more information.'
        else:
            logger.warning(f'Missing optional fields from cmdb records from {company_name} at {site_name}. Continuing reconciliation...')
    
    # parse tree and recreate as dictionary
    dict_tree = {}
    tree = ET.fromstring(prtg_instance.get_sensortree(group_id))
    groups = tree.find('sensortree').find('nodes').find('group')
    for group in groups.findall('group'):
        if group.find('name').text == 'Computacenter Infrastructure':
            dict_tree['Computacenter Infrastructure'] = group.find('id').text
        else:
            dict_tree['Customer Managed Infrastructure'] = {'id': group.find('id').text, 'stages': {}}
            for stage in group.findall('group'):
                dict_tree['Customer Managed Infrastructure']['stages'][stage.find('name').text] = {'id': stage.find('id').text, 'classes': {}}
                for sys_class in stage.findall('group'):
                        dict_tree['Customer Managed Infrastructure']['stages'][stage.find('name').text]['classes'][sys_class.find('name').text] = sys_class.find('id').text

    # recreate list as dictionary of id's for faster comparisons
    only_in_prtg = {}
    for device in prtg_devices:
        only_in_prtg[str(device['objid'])] = device

    # find symmetric difference by
    #   - removing from prtg list (exist in both)
    #   - create new snow list (unique to snow)
    #   - what's left in prtg list (unique to prtg)
    only_in_snow = []
    for snow_ci in snow_cis:
        if str(snow_ci['u_prtg_id']) in only_in_prtg:
            only_in_prtg.pop(snow_ci['u_prtg_id'])
        else:
            only_in_snow.append(snow_ci)
    

    # remove devices not in snow
    for device_id, _ in only_in_prtg.items():
        prtg_instance.delete_object(device_id)
    
    # add devices not in prtg
    for device in only_in_snow:
        try:
            stage = dict_tree['Customer Managed Infrastructure']['stages'][device['u_used_for']]
        except KeyError:
            # stage group does not exist; create stage group first
            new_stage_id = prtg_instance.add_group(device['u_used_for'], dict_tree['Customer Managed Infrastructure']['id'])
            prtg_instance.resume_object(new_stage_id)
            dict_tree['Customer Managed Infrastructure']['stages'][device['u_used_for']] = {'id': new_stage_id, 'classes': {}}
            stage = dict_tree['Customer Managed Infrastructure']['stages'][device['u_used_for']]
        try:
            sys_class = stage['classes'][device['sys_class_name']]
        except KeyError:
            # class group does not exist; create class group first
            new_class_id = prtg_instance.add_group(device['sys_class_name'], stage['id'])
            prtg_instance.resume_object(new_class_id)
            stage['classes'][device['sys_class_name']] = new_class_id
            sys_class = stage['classes'][device['sys_class_name']]

        device_id = prtg_instance.add_device(device['name'], sys_class, 
                                 device['ip_address'] if device['ip_address'] else device['u_host_name'])
        snow_api.update_prtg_id(device['sys_id'], device_id)
        if resume:
            prtg_instance.resume_object(device_id)
        snow_link = snow_api.ci_url(device['sys_id'])
        prtg_instance.edit_service_url(device_id, snow_link)
        prtg_instance.edit_tags(device_id, [device['u_used_for'].replace(' ', '-'), device['sys_class_name'].replace(' ', '-')])
    
    # Remove empty groups after removing devices. Order is important: if removing a subgroup causes
    # a parent group to become empty, the subgroup has to be checked first.

    # remove classes that are empty
    tree_post_action = ET.fromstring(prtg_instance.get_sensortree(group_id))
    group_post_action = tree_post_action.find('sensortree').find('nodes').find('group')
    for group in group_post_action.findall('./group/group/group'):
        if group.find('device') is None:
            prtg_instance.delete_object(group.find('id').text)

    # remove stages that are empty
    tree_post_action = ET.fromstring(prtg_instance.get_sensortree(group_id))
    group_post_action = tree_post_action.find('sensortree').find('nodes').find('group')
    for group in group_post_action.findall('./group/group'):
        if group.find('group') is None:
            prtg_instance.delete_object(group.find('id').text)
