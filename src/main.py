import logging.handlers
import secrets
import sys
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, status, Query
from fastapi.security import APIKeyHeader
from loguru import logger
from pydantic import SecretStr

from config import config
from sync import compare_snow_prtg, init_prtg as init_prtg_mod, update_prtg
from prtg.api import PrtgApi
from prtg.exception import ObjectNotFound

# read and parse config file
LOG_LEVEL = config['local']['log_level'].upper()
SYSLOG = config['local'].getboolean('syslog')
SYSLOG_HOST = config['local']['sys_log_host']
SYSLOG_PORT = config['local'].getint('sys_log_port')
TOKEN = config['local']['token']
PRTG_BASE_URL = config['prtg']['base_url']
PRTG_USER = config['prtg']['username']
PRTG_PASSHASH = config['prtg']['passhash']
PRTG_IS_PASSHASH = config['prtg'].getboolean('is_passhash')

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
                  probe_is_site: bool = Form(False, description="Does not create site group if true"), 
                  prtg_url: str = Form('', description="URL of PRTG instance (defaults to dev instance)"), 
                  username: str = Form('', description="Username for PRTG instance above"), 
                  password: SecretStr = Form('', description="Password for PRTG instance above"), 
                  is_passhash: bool = Form(False, description="Password above is passhash if true"), 
                  https_verify: bool = Form(True, description="Will verify SSL certificate for PRTG instance if true")):
    if prtg_url and username and password:
        try:
            # remove trailing '/' in URL
            prtg_url = prtg_url.rstrip('/')
            # custom PRTG instance
            if is_passhash:
                prtg_instance = PrtgApi(prtg_url, username=username, passhash=password.get_secret_value(), requests_verify=https_verify)
            else:
                prtg_instance = PrtgApi(prtg_url, username=username, password=password.get_secret_value(), requests_verify=https_verify)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        if PRTG_IS_PASSHASH:
            prtg_instance = PrtgApi(PRTG_BASE_URL, username=PRTG_USER, passhash=PRTG_PASSHASH, requests_verify=https_verify)
        else:
            prtg_instance = PrtgApi(PRTG_BASE_URL, username=PRTG_USER, password=PRTG_PASSHASH, requests_verify=https_verify)
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
                      probe_is_site: bool = Query(False, description="Does not create site group if true"), 
                      prtg_url: str = Query('', description="URL of PRTG instance (defaults to dev instance)"), 
                      username: str = Query('', description="Username for PRTG instance above"), 
                      password: SecretStr = Query('', description="Password for PRTG instance above"), 
                      is_passhash: bool = Query(False, description="Password above is passhash if true"),
                      https_verify: bool = Query(True, description="Will verify SSL certificate for PRTG instance if true")):
    if prtg_url and username and password:
        # remove trailing '/' in URL
        prtg_url = prtg_url.rstrip('/')
        # customer PRTG instance
        if is_passhash:
            prtg_instance = PrtgApi(prtg_url, username=username, passhash=password.get_secret_value(), requests_verify=https_verify)
        else:
            prtg_instance = PrtgApi(prtg_url, username=username, password=password.get_secret_value(), requests_verify=https_verify)
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        if PRTG_IS_PASSHASH:
            prtg_instance = PrtgApi(PRTG_BASE_URL, username=PRTG_USER, passhash=PRTG_PASSHASH, requests_verify=https_verify)
        else:
            prtg_instance = PrtgApi(PRTG_BASE_URL, username=PRTG_USER, password=PRTG_PASSHASH, requests_verify=https_verify)
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
                      template_group: int = Form(..., description="ID of Template Group"), 
                      template_device: int = Form(..., description="ID of Template Device"), 
                      unpause: bool = Form(False, description="Unpauses devices after creation if true"), 
                      probe_is_site: bool = Form(False, description="Does not check for site group if true"), 
                      prtg_url: str = Form('', description="URL of PRTG instance (defaults to dev instance)"), 
                      username: str = Form('', description="Username for PRTG instance above"), 
                      password: SecretStr = Form('', description="Password for PRTG instance above"), 
                      is_passhash: bool = Form(False, description="Password above is passhash if true"),
                      https_verify: bool = Form(True, description="Will verify SSL certificate for PRTG instance if true")):
    '''**Please run _reconcileCompany_ first to see changes before confirming!**
    '''
    if prtg_url and username and password:
        # remove trailing '/' in URL
        prtg_url = prtg_url.rstrip('/')
        # custom PRTG instance
        prtg_instance = PrtgApi(prtg_url, username, password.get_secret_value(), template_group, template_device, is_passhash, https_verify)
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, template_group, template_device, PRTG_IS_PASSHASH, https_verify)
    try:
        errors = update_prtg.update_company(prtg_instance, company_name, site_name, unpause, probe_is_site)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=f'Could not find PRTG probe of {company_name} at {site_name}')
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')

@logger.catch
@app.get('/reconcileAll', dependencies=[Depends(authorize)], include_in_schema=False)
def reconcile_all(prtg_url: Optional[str]=None, 
                  username: Optional[str]=None, 
                  password: Optional[SecretStr]=None, 
                  is_passhash: bool=False,
                  https_verify: bool=True):
    if prtg_url and username and password:
        try:
            # custom PRTG instance
            prtg_instance = PrtgApi(prtg_url, username, password.get_secret_value(), is_passhash=is_passhash, requests_verify=https_verify)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH, requests_verify=https_verify)
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')
