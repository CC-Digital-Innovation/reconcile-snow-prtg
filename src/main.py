import logging.handlers
import secrets
import sys

from fastapi import Depends, FastAPI, Form, HTTPException, status, Query
from fastapi.security import APIKeyHeader
from loguru import logger

from config import config
from sync import compare_snow_prtg, init_prtg as init_prtg_mod, update_prtg
from prtg import ApiClient as PrtgClient
from prtg.auth import BasicAuth, BasicPasshash, BasicToken
from prtg.exception import ObjectNotFound
from snow import ApiClient as SnowClient

# read and parse config file
LOG_LEVEL = config['local']['log_level'].upper()
SYSLOG = config['local'].getboolean('syslog')
SYSLOG_HOST = config['local']['sys_log_host']
SYSLOG_PORT = config['local'].getint('sys_log_port')
TOKEN = config['local']['token']
PRTG_BASE_URL = config['prtg']['base_url']
# use get() method since some are optional
PRTG_USER = config['prtg'].get('username')
PRTG_PASSWORD = config['prtg'].get('password')
PRTG_PASSHASH = config['prtg'].get('passhash')
PRTG_TOKEN = config['prtg'].get('token')
SNOW_INSTANCE = config['snow']['snow_instance']
SNOW_USERNAME = config['snow']['api_user']
SNOW_PASSWORD = config['snow']['api_password']

def set_log_level(log_level):
    '''Configure logging level and syslog.'''
    if log_level == "QUIET":
        logger.disable(__name__)
    else:
        # remove default logger
        logger.remove()
        logger.add(sys.stderr, level=log_level)
        if SYSLOG:
            logger.add(logging.handlers.SysLogHandler(address = (SYSLOG_HOST, SYSLOG_PORT)), level=log_level)

set_log_level(LOG_LEVEL)

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

# Get SNOW API Client
snow_client = SnowClient(SNOW_INSTANCE, SNOW_USERNAME, SNOW_PASSWORD)

api_key = APIKeyHeader(name='X-API-Key')

def authorize(key: str = Depends(api_key)):
    if not secrets.compare_digest(key, TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token')

logger.info('Starting up XSAutomate API...')
app = FastAPI(title="Reconcile Snow & PRTG")

@logger.catch
@app.post('/init-prtg', dependencies=[Depends(authorize)])
def init_prtg(company_name: str = Form(..., description="Name of Company"), # Ellipsis means it is required
              site_name: str = Form(..., description="Name of Site (Location)"), 
              probe_id: int = Form(..., description="ID of Root Group (not to be confused with Probe Device)"), 
              unpause: bool = Form(False, description="Unpauses devices after creation if true"), 
              probe_is_site: bool = Form(False, description="If true, creates root group as the site")):
    try:
        response = init_prtg_mod.init_prtg_from_snow(prtg_instance, company_name, site_name, probe_id, unpause, probe_is_site)
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred')
    else:
        if response:
            raise HTTPException(status_code=400, detail=response)
        return 'Successfully initialized PRTG devices from SNOW.'

@logger.catch
@app.get('/reconcile-company', dependencies=[Depends(authorize)])
def reconcile_company(company_name: str = Query(..., description="Name of Company"), 
                      site_name: str = Query(..., description="Name of Site (Location)"), 
                      probe_is_site: bool = Query(False, description="If true, consider root group as the site")):
    try:
        errors = compare_snow_prtg.compare(prtg_instance, company_name, site_name, probe_is_site)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=e)
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')
    else:
        if errors:
            return f'Successfully checked company {company_name} at {site_name} with {errors} errors found. Report will be sent out momentarily.'
        elif errors == 0:
            return f'Successfully checked company {company_name} at {site_name} with {errors} errors. No report created.'
        else:
            raise HTTPException(status_code=400, detail=f'No PRTG managed devices found.')

@logger.catch
@app.put('/confirm-reconcile', dependencies=[Depends(authorize)])
def confirm_reconcile(company_name: str = Form(..., description="Name of Company"), 
                      site_name: str = Form(..., description="Name of Site (Location)"),
                      unpause: bool = Form(False, description="Unpauses devices after creation if true"), 
                      probe_is_site: bool = Form(False, description="Does not check for site group if true")):
    '''**Please run _reconcileCompany_ first to see changes before confirming!**
    '''
    try:
        errors = update_prtg.update_company(prtg_instance, company_name, site_name, unpause, probe_is_site)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=f'Could not find PRTG probe of {company_name} at {site_name}')
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')

@logger.catch
@app.get('/reconcileAll', dependencies=[Depends(authorize)], include_in_schema=False)
def reconcile_all():
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')
