import html
import json
import logging.handlers
import os
import secrets
import sys
from pathlib import PurePath
from tempfile import SpooledTemporaryFile

import anytree
import dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, status
from fastapi.security import APIKeyHeader
from loguru import logger
from prtg import ApiClient as PrtgClient
from prtg.auth import BasicAuth, BasicPasshash, BasicToken
from prtg.exception import ObjectNotFound
from pydantic import SecretStr
from pysnow.exceptions import MultipleResults, NoResults
from requests.exceptions import HTTPError

import report
import sync
from alt_email import EmailApi, EmailHeaderAuth
from alt_prtg import PrtgController
from alt_prtg.models import Device
from snow import ApiClient as SnowClient
from snow import SnowController
from snow.adapter import get_prtg_tree_adapter
from snow.models import DeviceBody, Log, State

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
        prtg_url: str | None = Form(None, description='Set a different PRTG instance. Must include HTTP/S protocol, e.g. https://prtg.instance.com.'),
        prtg_token: SecretStr | None = Form(None, description='API token to authenticate with a different PRTG instance (username not necessary).'),
        prtg_username: SecretStr | None = Form(None, description='Username to authenticate with a different PRTG instance (password or passhash needed)'),
        prtg_password: SecretStr | None = Form(None, description='Password to authenticate with a different PRTG instance (username needed)'),
        prtg_passhash: SecretStr | None = Form(None, description='Passhash to authenticate with a different PRTG instance (username needed)'),
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
@app.post('/syncSite', dependencies=[Depends(authorize)], status_code=status.HTTP_202_ACCEPTED)
def sync_site(background_tasks: BackgroundTasks,
        company_name: str = Form(..., description='Name of Company'), # Ellipsis means it is required
        site_name: str = Form(..., description='Name of Site (Location)'),
        root_id: int = Form(..., description='ID of root group (not to be confused with Probe Device)'),
        root_is_site: bool = Form(False, description='Set to true if root group is the site'),
        delete: bool = Form(False, description='If true, delete inactive devices. Defaults to false.'),
        email: str | None = Form(None, description='Sends result to email address.'),
        prtg_client: PrtgClient = Depends(custom_prtg_parameters),
        request_id: str | None = Form(None, description='Optional ID to return as response.')):
    logger.info(f'Syncing for {company_name} at {site_name}...')
    logger.debug(f'Company name: {company_name}, Site name: {site_name}, Root ID: {root_id}, Is Root Site: {root_is_site}')
    # clean str inputs
    company_name = html.escape(company_name, quote=False)
    site_name = html.escape(site_name, quote=False)
    # run long sync process and email in background
    background_tasks.add_task(sync_site_and_email_task, company_name, site_name, root_id, root_is_site, delete, email, prtg_client, request_id)

@logger.catch
@app.post('/syncAllSites', dependencies=[Depends(authorize)])
def sync_all_sites(company_name: str = Form(..., description='Name of Company'), # Ellipsis means it is required
        root_id: int = Form(..., description='ID of root group (not to be confused with Probe Device)'),
        delete: bool = Form(False, description='If true, delete inactive devices. Defaults to false.'),
        email: str | None = Form(None, description='Sends result to email address.'),
        prtg_client: PrtgClient = Depends(custom_prtg_parameters)):
    logger.info(f'Syncing all sites for {company_name}...')
    logger.debug(f'Company name: {company_name}, Root ID: {root_id}')
    # clean str input
    company_name = html.escape(company_name, quote=False)
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
        devices_deleted = []
        for location in locations:
            config_items = snow_controller.get_config_items(company, location)
            try:
                expected_tree = get_prtg_tree_adapter(company, location, config_items, snow_controller, False, MIN_DEVICES)
            except ValueError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

            # Sync trees
            try:
                curr_added, curr_deleted = sync.sync_trees(expected_tree, current_tree, snow_controller, prtg_controller, delete=delete)
            except (sync.RootMismatchException, ValueError) as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
            devices_added.extend(curr_added)
            devices_deleted.extend(curr_deleted)

        # No changes found, return
        if not devices_added and not devices_deleted:
            return f'No devices added or deleted for {company_name}. Existing devices and their fields may have been updated.'

        # Send Report
        if email and email_client:
            logger.info('Sending report to email...')
            subject = f'XSAutomate: Synced all sites for {company_name}'
            report_name = f'Successfully Synced all sites for {company_name}'
            table_title = []

            # Create temporary file for report
            with SpooledTemporaryFile() as added, SpooledTemporaryFile() as deleted:
                files = []
                if devices_added:
                    # build added device report table
                    modeled_added_devices = [report.AddedDeviceModel.from_device(device, prtg_client) for device in devices_added]
                    added_devices_table = [device._asdict() for device in modeled_added_devices]
                    # requires encoding because json module only dumps in str,
                    # requests module recommends opening in binary mode,
                    # and temp files can only be opened in one mode
                    added.write(json.dumps(added_devices_table).encode())
                    # reset position before sending
                    added.seek(0)
                    # add table title
                    table_title.append(f'Devices Added: {len(devices_added)}')
                    # add file
                    files.append(('added.json', added))

                if devices_deleted:
                    # build deleted device report table
                    modeled_deleted_devices = [report.DeletedDeviceModel.from_device(device) for device in devices_deleted]
                    deleted_devices_table = [device._asdict() for device in modeled_deleted_devices]
                    deleted.write(json.dumps(deleted_devices_table).encode())
                    deleted.seek(0)
                    table_title.append(f'Devices Deleted: {len(devices_deleted)}')
                    files.append(('deleted.json', deleted))
                try:
                    email_client.email(email, subject, report_name=report_name, table_title=table_title, files=files)
                except HTTPError as e:
                    logger.exception('Unhandled error from email API: ' + str(e))
                    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                                        'Sync has successfully completed but an unexpected error occurred when sending the email.')
            logger.info('Successfully sent report to email.')
        logger.info(f'Successfully added {len(devices_added)} and deleted {len(devices_deleted)} devices to {company_name}.')
    except (HTTPException, HTTPError) as e:
        # Reraise already handled exception
        logger.error(e)
        raise e
    except Exception as e:
        # Catch all other unhandled exceptions
        logger.exception('Unhandled error: ' + str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, 'An unexpected error occurred.')
    return f'Successfully added {len(devices_added)} and deleted {len(devices_deleted)} devices to {company_name}.'

@logger.catch
@app.patch("/syncDevice", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(authorize)])
def sync_device(device_body: DeviceBody, background_tasks: BackgroundTasks):
    # run long sync process and email in background
    background_tasks.add_task(sync_device_task, device_body)

def log_error_console_and_snow(request_id: str, error_msg: str):
    logger.error(error_msg)
    if request_id is not None:
        error_log = Log(request_id, State.FAILED, error_msg)
        snow_controller.post_log(error_log)

def sync_site_and_email_task(company_name, site_name, root_id, root_is_site, delete, email, prtg_client, request_id):
    """to be ran using FastAPI's BackgroundTasks"""
    # global try to log unhandled exceptions
    try:
        # Get expected tree based on company and location
        try:
            company = snow_controller.get_company_by_name(company_name)
        except (NoResults, MultipleResults) as e:
            log_error_console_and_snow(request_id, str(e) + f' for company {company_name}')
            return  # simply return since it's a background task
        logger.info(f'Company "{company_name} found in SNOW."')
        try:
            location = snow_controller.get_location_by_name(site_name)
        except (NoResults, MultipleResults) as e:
            log_error_console_and_snow(request_id, str(e) + f' for location {site_name}')
            return
        logger.info(f'Location "{site_name}" found in SNOW.')
        config_items = snow_controller.get_config_items(company, location)
        try:
            expected_tree = get_prtg_tree_adapter(company, location, config_items, snow_controller, root_is_site, MIN_DEVICES)
        except ValueError as e:
            log_error_console_and_snow(request_id, str(e))
            return

        prtg_controller = PrtgController(prtg_client)
        # Get current tree
        try:
            group = prtg_controller.get_probe(root_id)
        except ObjectNotFound:
            try:
                group = prtg_controller.get_group(root_id)
            except ObjectNotFound as e:
                log_error_console_and_snow(request_id, str(e))
                return
        logger.info(f'Group with ID {root_id} found in PRTG.')
        if not group.name.startswith(expected_tree.prtg_obj.name):
            log_error_console_and_snow(request_id, f'Root ID {root_id} returns object named "{group.name}" but does not start with expected name "{expected_tree.prtg_obj.name}".')
            return
        current_tree = prtg_controller.get_tree(group)

        # Sync trees
        try:
            devices_added, devices_deleted = sync.sync_trees(expected_tree, current_tree, snow_controller, prtg_controller, delete=delete)
        except sync.RootMismatchException as e:
            log_error_console_and_snow(request_id, str(e))
            return

        # No changes found, return
        if not devices_added and not devices_deleted:
            no_change_log = Log(request_id, State.SUCCESS, f'No devices added or deleted for {company_name} at {site_name}. Existing devices and their fields may have been updated.')
            snow_controller.post_log(no_change_log)
            return

        # Send Report
        if email and email_client:
            logger.info('Sending report to email...')
            subject = f'XSAutomate: Synced {company_name} at {site_name}'
            report_name = f'Successfully Synced {company_name} at {site_name}'
            table_title = []

            # Create temporary file for report
            with SpooledTemporaryFile() as added, SpooledTemporaryFile() as deleted:
                files = []
                if devices_added:
                    # build added device report table
                    modeled_added_devices = [report.AddedDeviceModel.from_device(device, prtg_client) for device in devices_added]
                    added_devices_table = [device._asdict() for device in modeled_added_devices]
                    # requires encoding because json module only dumps in str,
                    # requests module recommends opening in binary mode,
                    # and temp files can only be opened in one mode
                    added.write(json.dumps(added_devices_table).encode())
                    # reset position before sending
                    added.seek(0)
                    # add table title
                    table_title.append(f'Devices Added: {len(devices_added)}')
                    # add file
                    files.append(('added.json', added))

                if devices_deleted:
                    # build deleted device report table
                    modeled_deleted_devices = [report.DeletedDeviceModel.from_device(device) for device in devices_deleted]
                    deleted_devices_table = [device._asdict() for device in modeled_deleted_devices]
                    deleted.write(json.dumps(deleted_devices_table).encode())
                    deleted.seek(0)
                    table_title.append(f'Devices Deleted: {len(devices_deleted)}')
                    files.append(('deleted.json', deleted))
                try:
                    email_client.email(email, subject, report_name=report_name, table_title=table_title, files=files)
                except HTTPError as e:
                    logger.exception('Unhandled error from email API: ' + str(e))
                    if request_id is not None:
                        success_except_email_log = Log(request_id, State.SUCCESS, f'Successfully added {len(devices_added)} and deleted {len(devices_deleted)} devices to {company_name} at {site_name}, but an unexpected error occurred when sending the email.')
                        snow_controller.post_log(success_except_email_log)
                    return
            logger.info('Successfully sent report to email.')
        logger.info(f'Successfully added {len(devices_added)} and deleted {len(devices_deleted)} devices to {company_name} at {site_name}.')
    except Exception as e:
        # Catch all other unhandled exceptions
        log_error_console_and_snow(request_id, 'Unhandled error: ' + str(e))
        return
    if request_id is not None:
        success_log = Log(request_id, State.SUCCESS, f'Successfully added {len(devices_added)} and deleted {len(devices_deleted)} devices to {company_name} at {site_name}.')
        snow_controller.post_log(success_log)

def sync_device_task(device_body: DeviceBody):
    """to be ran using FastAPI's BackgroundTasks"""
    auth = BasicToken(device_body.prtg_api_key)
    client = PrtgClient(device_body.prtg_url, auth)
    prtg_controller = PrtgController(client)
    logger.debug(f'PRTG URL: {device_body.prtg_url}')
    logger.debug(f'Device ID from payload: {device_body.device_id}.')
    ci = snow_controller.get_config_item(device_body.device_id)

    if ci.company is None or ci.location is None:
        log_error_console_and_snow(device_body.request_id, f'Cannot sync device {ci.name}. Missing company or location information in SNOW.')
        return  # simply return since it's a background task

    # get root group to avoid searching for it
    try:
        root = prtg_controller.get_probe(device_body.root_id)
    except ObjectNotFound:
        try:
            root = prtg_controller.get_group(device_body.root_id)
        except ObjectNotFound:
            log_error_console_and_snow(device_body.request_id, f'Cannot find root probe/group with root ID {device_body.root_id}.')
            return

    # get expected device and its path
    expected_node = get_prtg_tree_adapter(ci.company, ci.location, [ci], snow_controller, min_device=MIN_DEVICES)
    device_node = anytree.find(expected_node, filter_=lambda x: isinstance(x.prtg_obj, Device))
    device_path = device_node.path

    try:
        device = sync.sync_device(device_path, prtg_controller, snow_controller, root_group=root)
    except (ValueError, sync.RootMismatchException) as e:
        log_error_console_and_snow(device_body.request_id, str(e))
        return
    if device_body.request_id is not None:
        success_log = Log(device_body.request_id, State.SUCCESS, f'Successfully created/updated {device.name} with ID {device.id}.')
        snow_controller.post_log(success_log)
