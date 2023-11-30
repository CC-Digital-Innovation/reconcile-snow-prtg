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

from alt_email import EmailApi, EmailHeaderAuth
from alt_prtg import PrtgController
from report import get_add_device_model
from snow import ApiClient as SnowClient
from snow import SnowController, get_prtg_tree_adapter
from sync import sync_trees


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
        devices_added = sync_trees(expected_tree, current_tree, snow_controller, prtg_controller)

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
            devices_added.append(sync_trees(expected_tree, current_tree, snow_controller, prtg_controller))

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
