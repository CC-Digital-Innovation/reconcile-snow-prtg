import configparser
import csv
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from operator import itemgetter
from pathlib import PurePath

import requests
from loguru import logger

import email_report
import prtg_api
import snow_api

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

def get_csv_cis(file_name):
    '''Returns a list of dictionaries of the csv file'''
    with open(file_name) as stream:
        dict_reader = csv.DictReader(stream)
        return [row for row in dict_reader]

def create_file(company_name, group_id):
    '''Create csv file of snow and prtg devices to compare manually'''
    # remove whitespace and PascalCase
    file_name = ''.join([subname.capitalize() for subname in company_name.split()])
    with open(f'{file_name}-compare.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['PRTG Match', 'SNOW Name', 'SNOW URL', 'PRTG Name', 'PRTG URL', 'PRTG ID'])
        snow_cis = [(ci['name'], snow_api.ci_url(ci['sys_id'])) for ci in snow_api.get_cis(company_name)]
        snow_cis.sort(key=itemgetter(0))
        prtg_list = [(device['name'], prtg_api.device_url(device['objid'])) for device in prtg_api.get_devices(group_id)]
        prtg_list.sort(key=itemgetter(0))
        for snow_ci, prtg_device in zip(snow_cis, prtg_list):
            writer.writerow(['', snow_ci[0], snow_ci[1], prtg_device[0], prtg_device[1], prtg_device[2]])

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

def check_snow_ci(company_name, file_name):
    '''Validate snow configuration items from csv file'''
    # get snow ci
    snow_cis = snow_api.get_cis(company_name)
    # get csv ci
    csv_cis = get_csv_cis(file_name)
    
    # create report on mismatches
    missing_csv_ci = []
    found = False
    # compare ci in snow from csv
    for csv_ci in csv_cis:
        for i, snow_ci in enumerate(snow_cis):
            if csv_ci['name'].strip().lower() == snow_ci['name'].strip().lower():
                found = True
                snow_cis.pop(i)
                break
        if not found:
            logger.info('SNOW is missing device: ' + csv_ci['name'])
            missing_csv_ci.append(csv_ci)
        else:
            found = False
    # TODO consider duplicate ci in either list
    return missing_csv_ci

def compare(company_name, site_name, group_id=None):
    '''Compares SNOW and PRTG devices
    
    Returns
    -------
    int
        Number of issues. -1 return value means
        company and/or site could not be found
    '''
    # get snow devices
    snow_cis = snow_api.get_cis_by_site(company_name, site_name)
    # get prtg devices
    prtg_devices = None
    if group_id == -1:
        logger.warning(f'Could not find PRTG probe of company {company_name} at {site_name}')
    elif not group_id:
        group_id = prtg_api.get_probe_id(company_name, site_name)
        if not group_id:
            logger.warning(f'Could not find PRTG probe of company {company_name} at {site_name}')
        else:
            prtg_devices = prtg_api.get_devices(group_id)
    else:
        prtg_devices = prtg_api.get_devices(group_id)

    if not snow_cis and not prtg_devices:
        return -1

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
            device['category'] = prtg_api.get_obj_property(device['parentid'], 'name')
            stage_id = prtg_api.get_obj_status(device['parentid'], 'parentid')
            device['stage'] = prtg_api.get_obj_property(stage_id, 'name')
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
                    builder = MismatchBuilder(prtg_device=device['name'], prtg_link=prtg_api.device_url(device['objid']),
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
                    p_address = prtg_api.get_obj_property(device['objid'], 'host')
                    builder.check('IP Address', p_address, ci['ip_address'])

                    # tags
                    if ci['u_used_for'] not in device['tags'] or ci['u_category'] not in device['tags']:
                        builder.add('Tags', device['tags'], ' '.join((ci['u_used_for'], ci['u_category'])))

                    # priority
                    # builder.check('Priority', device['priority'], ci['u_priority'])

                    # serviceurl
                    builder.check('Service URL', prtg_api.get_obj_property(device['objid'], 'serviceurl'), snow_api.ci_url(ci['sys_id']))

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
                    combined_prtg_list.append((device['name'], prtg_api.device_url(device['objid'])))
    logger.debug(json.dumps(combined_prtg_list, indent=4))
    logger.debug('Devices with mismatched fields:')
    logger.debug(json.dumps(mismatch, indent=4))
    if combined_snow_list or combined_prtg_list or mismatch:
        email_report.send_report(company_name, site_name, combined_snow_list, combined_prtg_list, mismatch)
    # add number of mismatched FIELDS, not just total devices
    num_mismatch = sum((len(m['fields']) for m in mismatch))
    return len(combined_prtg_list) + len(combined_snow_list) + num_mismatch

def compare_with_attempts(company_name, site_name, group_id=None, attempts=config['local'].getint('attempts')):
    for attempt in range(attempts):
        try:
            return compare(company_name, site_name, group_id)
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            logger.warning(f'Failed to connect for company {company_name} at {site_name}. Retrying {attempt + 1}...')
    else:
        logger.warning(f'Failed to get company {company_name} at {site_name} after {attempts} attempts.')

def compare_all():
    with ThreadPoolExecutor(max_workers=config['local'].getint('max_threads')) as executor:
        tree = ET.fromstring(prtg_api.get_sensortree())
        groups = []
        groups.extend(tree.iter('group'))
        groups.extend(tree.iter('probenode'))
        compare_futures = {}
        for company in snow_api.get_companies():
            for site in snow_api.get_company_locations(company['name']):
                d_id = -1
                for element in groups:
                    name = f'[{company["name"]}] {site["name"]}'
                    if element.find('name').text == name:
                        d_id = element.get('id')
                        break
                if d_id:
                    compare_futures[executor.submit(compare_with_attempts, company['name'], site['name'], d_id)] = {'company': company['name'], 'site': site['name']}
                else:
                    logger.warning(f'Cannot find {company["name"]}] {site["name"]}')
        for future in as_completed(compare_futures):
            try:
                result = future.result()
            except Exception as e:
                logger.exception(f'Exception: {e}')
                compare_futures[future]['unknown'] = 'Internal Error'
            else:
                compare_futures[future]['result'] = result
        email_report.send_digest(compare_futures)