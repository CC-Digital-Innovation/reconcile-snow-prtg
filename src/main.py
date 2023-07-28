import configparser
import logging.handlers
import secrets
import sys
from pathlib import PurePath

from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.security import APIKeyHeader
from loguru import logger
from prtg import ApiClient as PrtgClient
from prtg.auth import BasicAuth, BasicPasshash, BasicToken
from prtg.exception import ObjectNotFound

from alt_prtg import PrtgController
from snow import ApiClient as SnowClient
from snow import SnowController, get_prtg_tree_adapter
from sync import sync_trees

# load config file
config = configparser.ConfigParser()
config.read(PurePath(__file__).with_name('config.ini'))

# read and parse config file
LOG_LEVEL = config['local'].get('log_level', 'INFO').upper()
SYSLOG_HOST = config['local'].get('sys_log_host', '')
SYSLOG_PORT = config['local'].getint('sys_log_port', 514)
TOKEN = config['local']['token']
MIN_DEVICES = config['local'].getint('min_devices', 0)
PRTG_BASE_URL = config['prtg']['base_url']
# use get() method since some are optional
PRTG_USER = config['prtg'].get('username')
PRTG_PASSWORD = config['prtg'].get('password')
PRTG_PASSHASH = config['prtg'].get('passhash')
PRTG_TOKEN = config['prtg'].get('token')
SNOW_INSTANCE = config['snow']['snow_instance']
SNOW_USERNAME = config['snow']['api_user']
SNOW_PASSWORD = config['snow']['api_password']

# Configure logger and syslog
if LOG_LEVEL == "QUIET":
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
    raise KeyError('Missing credentials for PRTG. Choose one of: (1) Token, (2) Username and password, (3) Username and passhash')
prtg_instance = PrtgClient(PRTG_BASE_URL, prtg_auth)
prtg_controller = PrtgController(prtg_instance)

# Get SNOW API Client
snow_client = SnowClient(SNOW_INSTANCE, SNOW_USERNAME, SNOW_PASSWORD)
snow_controller = SnowController(snow_client)

api_key = APIKeyHeader(name='X-API-Key')

def authorize(key: str = Depends(api_key)):
    if not secrets.compare_digest(key, TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token')

logger.info('Starting up XSAutomate API...')
app = FastAPI(title="Reconcile Snow & PRTG")

@logger.catch
@app.post('/sync', dependencies=[Depends(authorize)])
def sync(company_name: str = Form(..., description="Name of Company"), # Ellipsis means it is required
        site_name: str = Form(..., description="Name of Site (Location)"), 
        root_id: int = Form(..., description="ID of root group (not to be confused with Probe Device)"), 
        root_is_site: bool = Form(False, description="Set to true if root group is the site")):
    logger.info(f'Syncing for {company_name} at {site_name}...')
    logger.debug(f'Company name: {company_name}, Site name: {site_name}, Root ID: {root_id}, Is Root Site: {root_is_site}')
    try:
        # Get expected tree
        try:
            company = snow_controller.get_company_by_name(company_name)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        logger.info(f'Company "{company_name} found in SNOW."')
        try:
            location = snow_controller.get_location_by_name(site_name)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        logger.info(f'Location "{site_name}" found in SNOW.')
        config_items = snow_controller.get_config_items(company, location)
        try:
            expected_tree = get_prtg_tree_adapter(company, location, config_items, root_is_site, MIN_DEVICES)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        # Get current tree
        try:
            group = prtg_controller.get_group(root_id)
        except ObjectNotFound as e:
            raise HTTPException(status.HTTP_404_BAD_REQUEST, str(e))
        logger.info(f'Group with ID {root_id} found in PRTG.')
        current_tree = prtg_controller.get_tree(group)

        # Sync trees
        devices_created = sync_trees(expected_tree, current_tree, snow_controller, prtg_controller)
    except HTTPException as e:
        # Reraise already handled exception
        logger.error(e)
        raise e
    except Exception as e:
        # Catch all other unhandled exceptions
        logger.exception('Unhandled error: ' + str(e))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, 'An unexpected error occurred.')
    return f'Successfully added {len(devices_created)} devices to {company_name} at {site_name}.'
