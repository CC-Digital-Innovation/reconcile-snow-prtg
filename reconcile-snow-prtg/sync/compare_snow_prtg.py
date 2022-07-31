import json
import time

import email_report
import requests
import snow_api
from loguru import logger

from config import config
from prtg.exception import ProbeNotFound
from prtg.prtg_api import PRTGInstance

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

def compare(prtg_instance: PRTGInstance, company_name, site_name):
    '''Compares SNOW and PRTG devices
    
    Returns
    -------
    int
        Number of issues

    None
        No devices managed by prtg or could not find
        company/site in SNOW

    Raises
    ------
    ProbeNotFound
        Could not find PRTG probe
    '''
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

    mismatch = []

    # recreate list as dictionary of id's for faster comparisons
    only_in_prtg = {}
    for device in prtg_devices:
        only_in_prtg[str(device['objid'])] = device
    
    # Compare devices based on id.
    only_in_snow = []
    for snow_ci in snow_cis:
        try:
            device = only_in_prtg[snow_ci['u_prtg_id']]
            builder = MismatchBuilder(prtg_device=device['name'], prtg_link=prtg_instance.device_url(device['objid']),
                                      snow_device=snow_ci['name'], snow_link=snow_api.ci_url(snow_ci['sys_id']))
        except KeyError:
            only_in_snow.append(snow_ci)
            continue

        # check all other fields

        # location
        try:
            location_ci = snow_api.get_record(snow_ci['location']['link'])['result']
            s_street = location_ci['street'].replace('\r\n', ' ')
            s_city = location_ci['city'].replace('\r\n', ' ')
            s_state = location_ci['state'].replace('\r\n', ' ')
            try:
                s_country = snow_api.get_record(location_ci['u_country']['link'])['result']['name']
            except TypeError:
                s_country = ''
        except TypeError:
            logger.warning(f'Tried to access record but field location is string: {location_ci}')
            location_ci = snow_ci['location']
            s_street = s_city = s_state = s_country = ''
        try:
            p_street, p_city, p_state, p_country = [s.strip() for s in device['location_raw'].split(',')]
            builder.check('Street', p_street, s_street)
            builder.check('City', p_city, s_city)
            builder.check('State', p_state, s_state)
            builder.check('Country', p_country, s_country)
        except ValueError:
            builder.add('Location', device['location_raw'], ', '.join((s_street, s_city, s_state, s_country)))

        # stage, cc infrastructure devices does not have stage grandparent
        if 'stage' in device:
            builder.check('Used For', device['stage'], snow_ci['u_used_for'])

        # category, cc infrastructure devices does not have category parent
        if 'category' in device:
            builder.check('Class', device['category'], snow_ci['sys_class_name'])

        # ip address
        p_address = prtg_instance.get_obj_property(device['objid'], 'host')
        builder.check('IP Address', p_address, snow_ci['ip_address'])

        # tags
        if snow_ci['u_used_for'].replace(' ', '-') not in device['tags'] or snow_ci['sys_class_name'].replace(' ', '-') not in device['tags']:
            builder.add('Tags', device['tags'], ' '.join((snow_ci['u_used_for'].replace(' ', '-'), snow_ci['sys_class_name'].replace(' ', '-'))))

        # priority
        # builder.check('Priority', device['priority'], snow_ci['u_priority'])

        # serviceurl
        builder.check('Service URL', prtg_instance.get_obj_property(device['objid'], 'serviceurl'), snow_api.ci_url(snow_ci['sys_id']))

        #TODO credentials...

        if builder.mismatch:
            mismatch.append(builder.get_mismatch())
        
        # remove if exists in both list
        del only_in_prtg[snow_ci['u_prtg_id']]

    # create report on missing or mismatch
    logger.debug('SNOW devices not in PRTG:')
    combined_snow_list = []
    for device in only_in_snow:
        combined_snow_list.append((device['name'], snow_api.ci_url(device['sys_id'])))
    logger.debug(json.dumps(combined_snow_list, indent=4))
    logger.debug('PRTG devices not in SNOW:')
    combined_prtg_list = []
    for device in only_in_prtg.values():
        combined_prtg_list.append((device['name'], prtg_instance.device_url(device['objid'])))
    logger.debug(json.dumps(combined_prtg_list, indent=4))
    logger.debug('Devices with mismatched fields:')
    logger.debug(json.dumps(mismatch, indent=4))
    if combined_snow_list or combined_prtg_list or mismatch:
        email_report.send_report(company_name, site_name, combined_snow_list, combined_prtg_list, mismatch)
    # add number of mismatched FIELDS, not just total devices
    num_mismatch = sum((len(m['fields']) for m in mismatch))
    return len(combined_prtg_list) + len(combined_snow_list) + num_mismatch

def compare_with_attempts(prtg_instance, company_name, site_name, attempts=config['local'].getint('attempts'), sleep_time=config['local'].getint('retry_sleep_time')):
    for attempt in range(attempts):
        try:
            return compare(prtg_instance, company_name, site_name)
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            logger.warning(f'Failed to connect for company {company_name} at {site_name}. Retrying {attempt + 1}...')
            time.sleep(sleep_time)
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
