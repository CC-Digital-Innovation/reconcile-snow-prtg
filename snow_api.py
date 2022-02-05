import configparser
from pathlib import PurePath

import pysnow
import requests
from loguru import logger

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

# service now client
snow_client = pysnow.Client(instance=config['snow']['snow_instance'], user=config['snow']['api_user'], password=config['snow']['api_password'])

def get_u_category_labels():
    '''Returns a list of all device categories'''
    choices = snow_client.resource(api_path='/table/sys_choice')
    categories = choices.get(query={'element': 'u_category'})
    return sorted({category['label'] for category in categories.all()})

def get_u_used_for_labels():
    '''Returns a list of all u_used_for choices'''
    choices = snow_client.resource(api_path='/table/sys_choice')
    categories = choices.get(query={'element': 'u_used_for'})
    return sorted({category['label'] for category in categories.all()})

def get_companies():
    '''Returns a list of all companies'''
    companies = snow_client.resource(api_path='/table/core_company')
    query = (
        pysnow.QueryBuilder()
        .field('active').equals('true')
        .AND().field('name').order_ascending()
    )
    response = companies.get(query=query)
    return response.all()

def get_company_sites(company_name):
    '''Return all sites of a company'''
    sites = snow_client.resource(api_path='/table/cmn_location')
    #TODO use u_site_name when it is consistent (instead of 'name' field)
    query = (
        pysnow.QueryBuilder()
        .field('u_active').equals('true')
        .AND().field('company.name').equals(company_name)
    )
    response = sites.get(query=query)
    return response.all()

def get_company(company_name):
    '''Return a company record
    
    Raise
    -----
    pysnow.exceptions.MultipleResults
        Could not find record

    pysnow.exceptions.NoResults
        More than one record found
    '''
    companies = snow_client.resource(api_path='/table/core_company')
    query = (
        pysnow.QueryBuilder()
        .field('active').equals('true')
        .AND().field('name').equals(company_name)
    )
    response = companies.get(query=query, stream=True)
    return response.one()

def get_location(site_name):
    '''Return a site location
    
    Raise
    -----
    pysnow.exceptions.MultipleResults
        Could not find record

    pysnow.exceptions.NoResults
        More than one record found
    '''
    locations = snow_client.resource(api_path='/table/cmn_location')
    #TODO use u_site_name when it is consistent (instead of 'name' field)
    query = (
        pysnow.QueryBuilder()
        .field('u_active').equals('true')
        .AND().field('name').equals(site_name)
    )
    response = locations.get(query=query, stream=True)
    return response.one()

def get_company_locations(company_name):
    '''Return a list of all locations of a company'''
    locations = snow_client.resource(api_path='/table/cmn_location')
    query = (
        pysnow.QueryBuilder()
        .field('u_active').equals('true')
        .AND().field('company.name').equals(company_name)
        .AND().field('state').order_ascending()
        .AND().field('city').order_ascending()
    )
    response = locations.get(query=query)
    return response.all()

def get_cis_filtered(company_name, location, category, stage):
    '''Returns a list of all devices filtered by company, location, and category'''
    cis = snow_client.resource(api_path='/table/cmdb_ci')
    query = (
        pysnow.QueryBuilder()
        .field('company.name').equals(company_name)
        .AND().field('name').order_ascending()
        .AND().field('install_status').equals('1')      # Installed
        .OR().field('install_status').equals('101')     # Active
        .OR().field('install_status').equals('107')     # Duplicate installed
        .AND().field('location.name').equals(location)
        .AND().field('u_category').equals(category)
        .AND().field('u_used_for').equals(stage)
        .AND().field('u_cc_type').not_equals('Out of Scope')
        .AND().field('u_prtg_implementation').equals('true')
        .AND().field('u_prtg_instrumentation').equals('false')
    )
    response = cis.get(query=query)
    return response.all()

def get_cis_by_site(company_name, site_name):
    '''Returns a list of all devices from a company'''
    cis = snow_client.resource(api_path='/table/cmdb_ci')
    cis.parameters.display_value = True
    query = (
        pysnow.QueryBuilder()
        .field('company.name').equals(company_name)
        .AND().field('name').order_ascending()
        .AND().field('install_status').equals('1')      # Installed
        .OR().field('install_status').equals('101')     # Active
        .OR().field('install_status').equals('107')     # Duplicate installed
        .AND().field('location.name').equals(site_name)
        .AND().field('u_cc_type').not_equals('Out of Scope')
        .AND().field('u_prtg_implementation').equals('true')
    )
    response = cis.get(query=query)
    return response.all()

def get_internal_cis_by_site(company_name, site_name):
    '''Returns a list of all interal devices to monitor for a company'''
    cis = snow_client.resource(api_path='/table/cmdb_ci')
    cis.parameters.display_value = True
    query = (
        pysnow.QueryBuilder()
        .field('company.name').equals(company_name)
        .AND().field('name').order_ascending()
        .AND().field('install_status').equals('1')      # Installed
        .OR().field('install_status').equals('101')     # Active
        .OR().field('install_status').equals('107')     # Duplicate installed
        .AND().field('location.name').equals(site_name)
        .AND().field('u_cc_type').not_equals('Out of Scope')
        .AND().field('u_prtg_implementation').equals('true')
        .AND().field('u_prtg_instrumentation').equals('true')
    )
    response = cis.get(query=query)
    return response.all()

def get_customer_cis_by_site(company_name, site_name):
    '''Returns a list of all customer devices for a company'''
    cis = snow_client.resource(api_path='/table/cmdb_ci')
    cis.parameters.display_value = True
    query = (
        pysnow.QueryBuilder()
        .field('company.name').equals(company_name)
        .AND().field('name').order_ascending()
        .AND().field('install_status').equals('1')      # Installed
        .OR().field('install_status').equals('101')     # Active
        .OR().field('install_status').equals('107')     # Duplicate installed
        .AND().field('location.name').equals(site_name)
        .AND().field('u_cc_type').not_equals('Out of Scope')
        .AND().field('u_prtg_implementation').equals('true')
        .AND().field('u_prtg_instrumentation').equals('false')
    )
    response = cis.get(query=query)
    return response.all()

def decrypt_password(sys_id):
    url = f'https://expertservicestest.service-now.com/api/fuss2/ci_password/{sys_id}/getcipassword'
    headers = {'Authorization': config['snow']['api_key']}
    response = requests.get(url, headers=headers)
    logger.debug(response.text)
    return response.json()['result']['fs_password']

def ci_url(sys_id):
    return f'{config["snow"]["base_url"]}/cmdb_ci?sys_id={sys_id}'

def get_record(link):
    with requests.Session() as s:
        s.auth = (config['snow']['api_user'], config['snow']['api_password'])
        response = s.get(link)
    return response.json()
