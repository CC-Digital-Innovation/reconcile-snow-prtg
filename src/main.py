import json
import logging.handlers
import os
import secrets
import sys
from dataclasses import asdict
from pathlib import PurePath
from tempfile import SpooledTemporaryFile
from typing import Union

import dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.security import APIKeyHeader
from loguru import logger
from prtg import ApiClient as PrtgClient
from prtg.auth import BasicAuth, BasicPasshash, BasicToken
from prtg.exception import ObjectNotFound
from pydantic import SecretStr
from pysnow.exceptions import MultipleResults, NoResults
from requests.exceptions import HTTPError
import copy

from alt_email import EmailApi, EmailHeaderAuth
from alt_prtg import PrtgController
from report import get_add_device_model
from snow import ApiClient as SnowClient
from snow import SnowController, get_prtg_tree_adapter
from sync import sync_trees, RootMismatchException

from datetime import datetime
from pytz import timezone

from pydantic import BaseModel

#

# load secrets from .env
# loaded secrets will not overwrite existing environment variables
dotenv.load_dotenv(PurePath(__file__).with_name('.env'))

# Local
LOG_LEVEL = os.getenv('LOGGING_LEVEL', 'INFO').upper()
SYSLOG_HOST = os.getenv('SYSLOG_HOST')
if SYSLOG_HOST:
    SYSLOG_PORT = int(os.getenv('SYSLOG_PORT', 514))
TOKEN = os.environ['TOKEN']
MIN_DEVICES = int(os.environ['PRTG_MIN_DEVICES'])

# PRTG
PRTG_BASE_URL = os.environ['PRTG_URL']
prtg_verify = os.getenv('PRTG_VERIFY', 'true').lower()
PRTG_VERIFY = False if prtg_verify == 'false' else True
# use get() method since only one access method is required
PRTG_USER = os.getenv('PRTG_USER')
PRTG_PASSWORD = os.getenv('PRTG_PASSWORD')
PRTG_PASSHASH = os.getenv('PRTG_PASSHASH')
PRTG_TOKEN = os.getenv('PRTG_TOKEN')

# SNOW
SNOW_INSTANCE = os.environ['SNOW_INSTANCE']
SNOW_USERNAME = os.environ['SNOW_USER']
SNOW_PASSWORD = os.environ['SNOW_PASSWORD']


# Email
EMAIL_API = os.getenv('EMAIL_URL')
if EMAIL_API:
    EMAIL_TOKEN = os.environ['EMAIL_TOKEN']

# Configure logger and syslog
if LOG_LEVEL == 'QUIET':
    logger.disable(__name__)
else:
    # remove default logger
    logger.remove()
    logger.add(sys.stderr, level=LOG_LEVEL)
    if SYSLOG_HOST:
        logger.add(logging.handlers.SysLogHandler(address = (SYSLOG_HOST, SYSLOG_PORT)), level=LOG_LEVEL)

# Get PRTG API client
if PRTG_TOKEN:
    prtg_auth = BasicToken(PRTG_TOKEN)
elif PRTG_USER and PRTG_PASSHASH:
    prtg_auth = BasicPasshash(PRTG_USER, PRTG_PASSHASH)
elif PRTG_USER and PRTG_PASSWORD:
    prtg_auth = BasicAuth(PRTG_USER, PRTG_PASSWORD)
else:
    raise KeyError('Missing credentials for default PRTG instance. Choose one of: (1) token, (2) username and password, (3) username and passhash')

# Get SNOW API Client
snow_client = SnowClient(SNOW_INSTANCE, SNOW_USERNAME, SNOW_PASSWORD)
snow_controller = SnowController(snow_client)

# Create email client if desired
email_client = EmailApi(EMAIL_API, EmailHeaderAuth(EMAIL_TOKEN)) if EMAIL_API else None

api_key = APIKeyHeader(name='X-API-Key')

# dependency injection for all endpoints that need authentication
def authorize(key: str = Depends(api_key)):
    if not secrets.compare_digest(key, TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token')

# dependency injection for all endpoints that accept a custom prtg instance
def custom_prtg_parameters(
        prtg_url: Union[str, None] = Form(None, description='Set a different PRTG instance. Must include HTTP/S protocol, e.g. https://prtg.instance.com.'),
        prtg_token: Union[SecretStr, None] = Form(None, description='API token to authenticate with a different PRTG instance (username not necessary).'),
        prtg_username: Union[SecretStr, None] = Form(None, description='Username to authenticate with a different PRTG instance (password or passhash needed)'),
        prtg_password: Union[SecretStr, None] = Form(None, description='Password to authenticate with a different PRTG instance (username needed)'),
        prtg_passhash: Union[SecretStr, None] = Form(None, description='Passhash to authenticate with a different PRTG instance (username needed)'),
        prtg_verify: bool = Form(True, description='Validate server certificate if set to true (default).')):
    # Check if custom PRTG instance
    if prtg_url:
        # Clean URL
        prtg_url = prtg_url.strip().rstrip('/')
        # Get authentication
        if prtg_token:
            new_prtg_auth = BasicToken(prtg_token.get_secret_value())
        elif prtg_username and prtg_passhash:
            new_prtg_auth = BasicPasshash(prtg_username.get_secret_value(), prtg_passhash.get_secret_value())
        elif prtg_username and prtg_password:
            new_prtg_auth = BasicAuth(prtg_username.get_secret_value(), prtg_password.get_secret_value())
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Different PRTG instance entered but missing credentials. Choose one of: (1) Token, (2) Username \
                                and password, (3) Username and passhash')
        logger.info(f'Using custom PRTG instance {prtg_url}.')
        return PrtgClient(prtg_url, new_prtg_auth, requests_verify=prtg_verify)
    # use default PRTG instance
    return PrtgClient(PRTG_BASE_URL, prtg_auth, requests_verify=PRTG_VERIFY)


logger.info('Starting up XSAutomate API...')
desc = f'Defaults to the "{PRTG_BASE_URL.split("://")[1]}" instance. In order to use a different PRTG instance, enter the URL and credential parameters before\
      executing an endpoint. To authenticate for a different PRTG instance, enter one of: (1) token, (2) username and password, or (3) username and passhash.'
app = FastAPI(title='Reconcile Snow & PRTG', description=desc)

@logger.catch
@app.post('/sync', dependencies=[Depends(authorize)])
def sync(company_name: str = Form(..., description='Name of Company'), # Ellipsis means it is required
        site_name: str = Form(..., description='Name of Site (Location)'),
        root_id: int = Form(..., description='ID of root group (not to be confused with Probe Device)'),
        root_is_site: bool = Form(False, description='Set to true if root group is the site'),
        email: Union[str, None] = Form(None, description='Sends result to email address.'),
        prtg_client: PrtgClient = Depends(custom_prtg_parameters)):
    logger.info(f'Syncing for {company_name} at {site_name}...')
    logger.debug(f'Company name: {company_name}, Site name: {site_name}, Root ID: {root_id}, Is Root Site: {root_is_site}')
    try:
        # Get expected tree
        try:
            company = snow_controller.get_company_by_name(company_name)
        except (NoResults, MultipleResults) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e) + f' for company {company_name}')
        logger.info(f'Company "{company_name} found in SNOW."')
        try:
            location = snow_controller.get_location_by_name(site_name)
        except (NoResults, MultipleResults) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e) + f' for location {site_name}')
        logger.info(f'Location "{site_name}" found in SNOW.')
        config_items = snow_controller.get_config_items(company, location)
        try:
            expected_tree = get_prtg_tree_adapter(company, location, config_items, root_is_site, MIN_DEVICES)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        prtg_controller = PrtgController(prtg_client)
        # Get current tree
        try:
            group = prtg_controller.get_probe(root_id)
        except ObjectNotFound:
            try:
                group = prtg_controller.get_group(root_id)
            except ObjectNotFound as e:
                raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        logger.info(f'Group with ID {root_id} found in PRTG.')
        current_tree = prtg_controller.get_tree(group)

        # Sync trees
        try:
            devices_added = sync_trees(expected_tree, current_tree, snow_controller, prtg_controller)
        except RootMismatchException as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        # No changes found, return
        if not devices_added:
            return f'No changes were found for {company_name} at {site_name}.'

        # Send Report
        if email and email_client:
            logger.info('Sending report to email...')
            subject = f'XSAutomate: Synced {company_name} at {site_name}'
            report_name = f'Successfully Synced {company_name} at {site_name}'
            table_title = [f'Devices Added: {len(devices_added)}']

            # Create temporary file for report
            with SpooledTemporaryFile() as report:
                modeled_added_devices = [get_add_device_model(device, prtg_client) for device in devices_added]
                added_devices_table = [asdict(device) for device in modeled_added_devices]
                # requires encoding because json module only dumps in str,
                # requests module recommends opening in binary mode,
                # and temp files can only be opened in one mode
                report.write(json.dumps(added_devices_table).encode())
                # reset position before sending
                report.seek(0)
                try:
                    email_client.email(email, subject, report_name=report_name, table_title=table_title, files=[('report.json', report)])
                except HTTPError as e:
                    logger.exception('Unhandled error from email API: ' + str(e))
                    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                                        'Sync has successfully completed but an unexpected error occurred when sending the email.')
            logger.info('Successfully sent report to email.')
        logger.info(f'Successfully added {len(devices_added)} devices to {company_name} at {site_name}.')
    except HTTPException as e:
        # Reraise already handled exception
        logger.error(e)
        raise e
    except Exception as e:
        # Catch all other unhandled exceptions
        logger.exception('Unhandled error: ' + str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, 'An unexpected error occurred.')
    return f'Successfully added {len(devices_added)} devices to {company_name} at {site_name}.'

@logger.catch
@app.post('/syncAllSites', dependencies=[Depends(authorize)])
def sync_all_sites(company_name: str = Form(..., description='Name of Company'), # Ellipsis means it is required
        root_id: int = Form(..., description='ID of root group (not to be confused with Probe Device)'),
        email: Union[str, None] = Form(None, description='Sends result to email address.'),
        prtg_client: PrtgClient = Depends(custom_prtg_parameters)):
    logger.info(f'Syncing all sites for {company_name}...')
    logger.debug(f'Company name: {company_name}, Root ID: {root_id}')
    try:
        try:
            company = snow_controller.get_company_by_name(company_name)
        except (NoResults, MultipleResults) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e) + f' for company {company_name}')
        logger.info(f'Company "{company_name} found in SNOW."')
        locations = snow_controller.get_company_locations(company.name)
        logger.info(f'{len(locations)} locations found in SNOW.')

        prtg_controller = PrtgController(prtg_client)
        # Get current tree
        try:
            group = prtg_controller.get_probe(root_id)
        except ObjectNotFound:
            try:
                group = prtg_controller.get_group(root_id)
            except ObjectNotFound as e:
                raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        logger.info(f'Group with ID {root_id} found in PRTG.')
        current_tree = prtg_controller.get_tree(group)

        devices_added = []
        for location in locations:
            config_items = snow_controller.get_config_items(company, location)
            try:
                expected_tree = get_prtg_tree_adapter(company, location, config_items, False, MIN_DEVICES)
            except ValueError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

            # Sync trees
            try:
                devices_added.extend(sync_trees(expected_tree, current_tree, snow_controller, prtg_controller))
            except RootMismatchException as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        # No changes found, return
        if not devices_added:
            return f'No changes were found for any location at {company_name}.'
        
        # Send Report
        if email and email_client:
            logger.info('Sending report to email...')
            subject = f'XSAutomate: Synced all sites for {company_name}'
            report_name = f'Successfully Synced all sites for {company_name}'
            table_title = [f'Devices Added: {len(devices_added)}']

            # Create temporary file for report
            with SpooledTemporaryFile() as report:
                modeled_added_devices = [get_add_device_model(device, prtg_client) for device in devices_added]
                added_devices_table = [asdict(device) for device in modeled_added_devices]
                # requires encoding because json module only dumps in str,
                # requests module recommends opening in binary mode,
                # and temp files can only be opened in one mode
                report.write(json.dumps(added_devices_table).encode())
                # reset position before sending
                report.seek(0)
                try:
                    email_client.email(email, subject, report_name=report_name, table_title=table_title, files=[('report.json', report)])
                except HTTPError as e:
                    logger.exception('Unhandled error from email API: ' + str(e))
                    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                                        'Sync has successfully completed but an unexpected error occurred when sending the email.')
            logger.info('Successfully sent report to email.')
        logger.info(f'Successfully added {len(devices_added)} devices to {company_name}.')
    except HTTPException as e:
        # Reraise already handled exception
        logger.error(e)
        raise e
    except Exception as e:
        # Catch all other unhandled exceptions
        logger.exception('Unhandled error: ' + str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, 'An unexpected error occurred.')
    return f'Successfully added {len(devices_added)} devices to {company_name}.'

@logger.catch
def set_prop_base(prtg_client,
                  objid: int,
                  hostname : str,
                  name_update : str,
                  location : str):
    try:
        prtg_client.set_hostname(objid, hostname)
    except HTTPException as e:
        logger.error(f"Hostname not set: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device host was not set successfully: {e}")
    try:
        prtg_client._set_obj_property_base(objid, 'name', name_update)
    except HTTPException as e:
        logger.error(f"Name not set: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device name was not set successfully: {e}")
    try:
        prtg_client.set_inherit_location_off(objid)
    except HTTPException as e:
        logger.error(f"Location not set: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device location was not set successfully: {e}")
    try:
        prtg_client.set_location(objid, location)
    except HTTPException as e:
        logger.error(f"Location not set: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device location was not set successfully: {e}")


class SnowData(BaseModel):
    # PRTG KEYS
    prtg_url: str
    prtg_api_key: str

    #PRTG Inputs
    objid: int
    hostname: str
    ip: str
    manufactuer_model : str
    manufacturer_number: str 
    location: str

    # Parent Group
    category: str = None
    prex_category: str 

    # Grandparent Group
    used_for: str = None
    prex_used_for: str 

    min_devices: int = None



def get_groups_by_group_id(client, group_id):
        """Get groups by parent group

        Args:
            group_id (Union[int, str]): id of parent group

        Returns:
            list[dict]: devices and their details
        """
        params = {'id': group_id}
        return client._get_groups_base(params)


def get_empty_group(client,groupid):
    # Check if the group has no devices in 
    get_devices = client.get_devices_by_group_id(groupid)
        
    return get_devices
        
@logger.catch
@app.post("/api/v3/snow_prtg/sync_device_to_group")
def sync_device_to_group_v2(snow_data: SnowData):
        
        try:
            name_update = snow_data.manufactuer_model + " " + snow_data.manufacturer_number + " (" + snow_data.ip + ")"

            try:
                auth = BasicToken(snow_data.prtg_api_key)
                client = PrtgClient(f'https://{snow_data.prtg_url}', auth, requests_verify=True)
            except HTTPException as e:
                logger.error(f"Error creating PRTG client: {e}")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Error creating PRTG client: {e}")
            
            # Case 1: Example case of Moving Used For Group: Moves the device to a "Category" group within the great grandparent group.
            #                                                Check if there is already a grandparent group with the name "[CN] [used_for]"

            #                                                If there is ---- > Check if it has the category group already---> If it does move the device to that category group ---> If it doesn't create the category group and move the device to that category group                                           
            #                                                If it doesn't have that grandparent group, create it and create the category group---> Move the device to that category group

                    # category =  None;
                    # prex_category = 'Server'; 
                    # used_for = 'Staging'; 
                    # prex_used_for = 'Production'; 
                    # Change the group
            try:
                # Get parent group of device for company brackets
                device = client.get_device(snow_data.objid)
                parent_group = client.get_group(device['parentid'])
                groupid_copy = copy.deepcopy(parent_group['objid'])
                grandparent_group = client.get_group(parent_group['parentid'])
                grandparent_groupid_copy = copy.deepcopy(grandparent_group['objid'])
                great_grandparent_group = client.get_group(grandparent_group['parentid'])
                company_brackets = parent_group["name"].split(" ")[0]

                if snow_data.category == None:
                    # Check if the used_for group exists
                    grandparent_used_for = company_brackets + " " + snow_data.used_for
                    category_group = company_brackets + " " + snow_data.prex_category  

                   # In the great_grandparent group, check if the grandparent group exists using the grandparent group name and the get_groups_by_id function
                    great_grandparent_groups = get_groups_by_group_id(client, great_grandparent_group['objid'])

                    dummy_grandparent_group_exist = False
                    for each_grandparent in great_grandparent_groups:
                        if each_grandparent['name'] == grandparent_used_for:
                            # Check if the category group exists in the grandparent group
                            dummy_grandparent_group_exist = True
                            dummy_category_exist = False
                            category_group_exist = get_groups_by_group_id(client, each_grandparent['objid'])

                            for each_category in category_group_exist:
                                if each_category['name'] == category_group:
                                    # Move the device to the category group
                                    client.move_object(snow_data.objid, each_category['objid'])
                                    set_prop_base(client,
                                                snow_data.objid, 
                                                snow_data.hostname, 
                                                name_update, 
                                                snow_data.location)
                                    if get_empty_group(client,groupid_copy) == []:
                                        client.delete_object(groupid_copy)
                                    if get_empty_group(client,grandparent_groupid_copy) == []:
                                        client.delete_object(grandparent_groupid_copy)
                                    dummy_category_exist = True
                                    break

                            if dummy_category_exist == False:
                            # It doesn't exist, create the category group within the grandparent group and move the device to it
                                category_group = client.add_group(category_group, each_grandparent['objid'])
                                # Move the device to the category group
                                client.move_object(snow_data.objid, category_group['objid'])
                                set_prop_base(client,
                                            snow_data.objid, 
                                            snow_data.hostname, 
                                            name_update, 
                                            snow_data.location)
                                if get_empty_group(client,groupid_copy) == []:
                                        client.delete_object(groupid_copy)
                                if get_empty_group(client,grandparent_groupid_copy) == []:
                                    client.delete_object(grandparent_groupid_copy)
                                break

                    
                    if dummy_grandparent_group_exist == False:
                        #Create the grandparent group and the category group and move the device to the category group
                        grandparent_used_for_group = client.add_group(grandparent_used_for, great_grandparent_group['objid'])
                        category_group = client.add_group(category_group, grandparent_used_for_group['objid'])
                        # Move the device to the category group
                        client.move_object(snow_data.objid, category_group['objid'])
                        set_prop_base(client,
                                    snow_data.objid, 
                                    snow_data.hostname, 
                                    name_update, 
                                    snow_data.location)
                        if get_empty_group(client,groupid_copy) == []:
                                client.delete_object(groupid_copy)
                        if get_empty_group(client,grandparent_groupid_copy) == []:
                            client.delete_object(grandparent_groupid_copy)
                
                    
            # Case 2: Example case of Moving Category Group: Moves the device to another group within the same grandparent group
             #                                                Check if the device has the parent group already, if it doesn't-----> Create it and move the device to it ----> if it does ----> Move it to the existing group parent_group                                                                                 
                    # category =  'Backup';
                    # prex_category = 'Server'; 
                    # used_for = None; 
                    # prex_used_for = 'Production'; 

            # Before you make any movements, check if the device is already in the location
                elif snow_data.used_for == None:
                        # Check if the category group exists
                        category_group = company_brackets + " " + snow_data.category
                        
                        #Check if the device has the parent group already
                        grandparent_category_exist = get_groups_by_group_id(client, grandparent_group['objid'])

                        dummy_category_group_exist = False
                        for each in grandparent_category_exist:
                            if each['name'] == category_group:
                                # Move the device to the category group
                                # Store the parentid of the group
                                client.move_object(snow_data.objid, each['objid'])
                                # Check if the group you moved from is empty
                                if get_empty_group(client,groupid_copy) == []:
                                    client.delete_object(groupid_copy)

                                set_prop_base(client,
                                            snow_data.objid, 
                                            snow_data.hostname, 
                                            name_update, 
                                            snow_data.location)
                                dummy_category_group_exist = True
                                break
                        if dummy_category_group_exist == False:
                            # Category doesn't exist, create the category group within the grandparent group and move the device to it
                            category_group = client.add_group(category_group, grandparent_group['objid'])
                            set_prop_base(client,
                                        snow_data.objid, 
                                        snow_data.hostname, 
                                        name_update, 
                                        snow_data.location)
                            # Move the device to the category group
                            client.move_object(snow_data.objid, category_group['objid'])
                            if get_empty_group(client,groupid_copy) == []:
                                client.delete_object(groupid_copy)
                        
                        
                                    

            except Exception as e:
                logger.error(f"Error getting grandparent group: {e}")
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Error getting grandparent group: {e}")



        except HTTPException as e:
            logger.error(f"Any HTTP EXCEPTION: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Error creating PRTG client: {e}")
        except Exception as e:
            logger.error(f"All Uncaught Exceptions: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Error creating PRTG client: {e}")