import configparser
import json
import time
from pathlib import PurePath

import requests
from loguru import logger

import email_report
import snow_api

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

class MismatchBuilder():
    def __init__(self, prtg_device, prtg_link, snow_device, snow_link):
        self.prtg_device = prtg_device
        self.prtg_link = prtg_link
        self.snow_device = snow_device
        self.snow_link = snow_link
        self.mismatch = {}

    def get_mismatch(self):
        return {
            'prtg_device': self.prtg_device,
            'prtg_link': self.prtg_link,
            'snow_device': self.snow_device,
            'snow_link': self.snow_link,
            'fields': self.mismatch
        }

    def check(self, field_name, prtg, snow):
        if prtg != snow:
            self.mismatch[field_name] = {
            'prtg': prtg, 
            'snow': snow
        }

    def add(self, field_name, prtg, snow):
        self.mismatch[field_name] = {
            'prtg': prtg, 
            'snow': snow
        }

def compare(prtg_instance, company_name, site_name):
    '''Compares SNOW and PRTG devices
    
    Returns
    -------
    int
        Number of issues

    None
        No devices managed by prtg

    Raises
    ------
    ValueError
        Could not find PRTG probe
    '''
    # get snow devices
    snow_cis = snow_api.get_cis_by_site(company_name, site_name)
    # get prtg devices
    group_id = prtg_instance.get_probe_id(company_name, site_name)
    if not group_id:
        logger.warning(f'Could not find PRTG probe of company {company_name} at {site_name}')
        prtg_devices = None
    else:
        prtg_devices = prtg_instance.get_devices(group_id)

    # not prtg managed
    if not snow_cis and not prtg_devices:
        return

    # prtg managed devices exist but probe could not be found
    if snow_cis and prtg_devices is None:
        raise ValueError(f'Could not find PRTG probe of company {company_name} at {site_name}')

    mismatch = []
    prtg_name_errors = []

    # group snow cis into buckets by manufacturer
    grouped_snow = {}
    for ci in snow_cis:
        try:
            manuf_ci = ci['manufacturer']['display_value']
        except TypeError:
            manuf_ci = ci["manufacturer"]
            logger.warning(f'Tried to access record but field manufacturer is string: {manuf_ci}')
        try:
            model_id_ci = ci['model_id']['display_value']
        except TypeError:
            model_id_ci = ci['model_id']
        # replace reference with just name to save future get_record()'s
        ci['manufacturer'] = manuf_ci
        ci['model_id'] = model_id_ci
        if manuf_ci:
            try:
                grouped_snow[manuf_ci].append(ci)
            except KeyError:
                grouped_snow[manuf_ci] = [ci]
        else:
            try:
                grouped_snow['Unknown'].append(ci)
            except KeyError:
                grouped_snow['Unknown'] = [ci]

    # group prtg devices into buckets by manufacturer
    grouped_prtg = {}
    if prtg_devices:
        for device in prtg_devices:
            names = device['name'].split()
            if len(names) < 3:
                logger.error(f'Could not parse name of device "{device["name"]}"')
                prtg_name_errors.append(device)
                continue
            # get other fields for comparison
            device['host_name'] = names[0]
            device['manufacturer'] = names[1]
            device['model_id'] = ' '.join(names[2:])
            device['category'] = prtg_instance.get_obj_property(device['parentid'], 'name')
            stage_id = prtg_instance.get_obj_status(device['parentid'], 'parentid')
            device['stage'] = prtg_instance.get_obj_property(stage_id, 'name')
            try:
                grouped_prtg[device['manufacturer']].append(device)
            except KeyError:
                grouped_prtg[device['manufacturer']] = [device]

    # compare device and its fields
    for snow_manuf, snow_list in grouped_snow.items():
        try:
            prtg_list = grouped_prtg[snow_manuf]
        except KeyError:
            continue
        for i, ci in enumerate(snow_list):
            if not ci:
                continue
            for j, device in enumerate(prtg_list):
                if not device:
                    continue
                if ' '.join((ci['u_host_name'], ci['manufacturer'], ci['model_id'])) == device['name']:   
                    builder = MismatchBuilder(prtg_device=device['name'], prtg_link=prtg_instance.device_url(device['objid']),
                                              snow_device=ci['name'], snow_link=snow_api.ci_url(ci['sys_id']))
                    # check all other fields

                    # location
                    try:
                        location_ci = snow_api.get_record(ci['location']['link'])['result']
                        s_street = location_ci['street']
                        s_city = location_ci['city']
                        s_state = location_ci['state']
                        try:
                            s_country = snow_api.get_record(location_ci['u_country']['link'])['result']['name']
                        except TypeError:
                            s_country = ''
                    except TypeError:
                        logger.warning(f'Tried to access record but field location is string: {location_ci}')
                        location_ci = ci['location']
                        s_street = s_city = s_state = s_country = ''
                    try:
                        p_street, p_city, p_state, p_country = [s.strip() for s in device['location_raw'].split(',')]
                        builder.check('Street', p_street, s_street)
                        builder.check('City', p_city, s_city)
                        builder.check('State', p_state, s_state)
                        builder.check('Country', p_country, s_country)
                    except ValueError:
                        builder.add('Location', device['location_raw'], ', '.join((s_street, s_city, s_state, s_country)))

                    # ip address
                    p_address = prtg_instance.get_obj_property(device['objid'], 'host')
                    builder.check('IP Address', p_address, ci['ip_address'])

                    # tags
                    if ci['u_used_for'] not in device['tags'] or ci['u_category'] not in device['tags']:
                        builder.add('Tags', device['tags'], ' '.join((ci['u_used_for'], ci['u_category'])))

                    # priority
                    # builder.check('Priority', device['priority'], ci['u_priority'])

                    # serviceurl
                    builder.check('Service URL', prtg_instance.get_obj_property(device['objid'], 'serviceurl'), snow_api.ci_url(ci['sys_id']))

                    #TODO credentials...

                    if builder.mismatch:
                        mismatch.append(builder.get_mismatch())
                    snow_list[i] = None
                    prtg_list[j] = None

    # create report on missing or mismatch
    logger.debug('SNOW devices not in PRTG:')
    combined_snow_list = []
    for group in grouped_snow.values():
        if group:
            for device in group:
                if device:
                    combined_snow_list.append((device['name'], snow_api.ci_url(device['sys_id'])))
    logger.debug(json.dumps(combined_snow_list, indent=4))
    logger.debug('PRTG devices not in SNOW:')
    combined_prtg_list = []
    for group in grouped_prtg.values():
        if group:
            for device in group:
                if device:
                    combined_prtg_list.append((device['name'], prtg_instance.device_url(device['objid'])))
    logger.debug(json.dumps(combined_prtg_list, indent=4))
    logger.debug('Devices with mismatched fields:')
    logger.debug(json.dumps(mismatch, indent=4))
    if combined_snow_list or combined_prtg_list or mismatch:
        email_report.send_report(company_name, site_name, combined_snow_list, combined_prtg_list, mismatch)
    # add number of mismatched FIELDS, not just total devices
    num_mismatch = sum((len(m['fields']) for m in mismatch))
    return len(combined_prtg_list) + len(combined_snow_list) + num_mismatch

def compare_with_attempts(prtg_instance, company_name, site_name, attempts=config['local'].getint('attempts')):
    for attempt in range(attempts):
        try:
            return compare(prtg_instance, company_name, site_name)
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            logger.warning(f'Failed to connect for company {company_name} at {site_name}. Retrying {attempt + 1}...')
            time.sleep(3)
    else:
        logger.warning(f'Failed to get company {company_name} at {site_name} after {attempts} attempts.')
        raise ConnectionError(f'Failed to get company {company_name} at {site_name} after {attempts} attempts.')

def compare_all(prtg_instance):
    results = []
    for company in snow_api.get_companies():
        for site in snow_api.get_company_locations(company['name']):
            result = {
                'company': company['name'],
                'site': site['name']
            }
            try:
                result['result'] = compare_with_attempts(prtg_instance, company['name'], site['name'])
            except (ConnectionError, ValueError) as e:
                result['error'] = str(e)
            except Exception as e:
                logger.exception(e)
                result['error'] = 'Internal Error'
            finally:
                results.append(result)
    email_report.send_digest(results)