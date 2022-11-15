import logging.handlers
import secrets
import sys
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from loguru import logger
from pydantic import SecretStr

from config import config
from sync import compare_snow_prtg, init_prtg, update_prtg
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
app = FastAPI()

@logger.catch
@app.post('/initPRTG', dependencies=[Depends(authorize)])
def init_prtg_req(companyName: str, 
                  siteName: str, 
                  probeId: int, 
                  templateGroup: int, 
                  templateDevice: int, 
                  unpause: bool=False, 
                  siteIsProbe: bool=False, 
                  prtgUrl: Optional[str]=None, 
                  username: Optional[str]=None, 
                  password: Optional[SecretStr]=None, 
                  isPasshash: bool=False,
                  httpsVerify: bool=True):
    if prtgUrl and username and password:
        try:
            # custom PRTG instance
            prtg_instance = PrtgApi(prtgUrl, username, password.get_secret_value(), templateGroup, templateDevice, isPasshash, httpsVerify)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, templateGroup, templateDevice, PRTG_IS_PASSHASH, httpsVerify)
    try:
        response = init_prtg.init_prtg_from_snow(prtg_instance, companyName, siteName, probeId, unpause, siteIsProbe)
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred')
    else:
        if response:
            raise HTTPException(status_code=400, detail=response)
        return 'Successfully initialized PRTG devices from SNOW.'

@logger.catch
@app.get('/reconcileCompany', dependencies=[Depends(authorize)])
def reconcile_company(companyName: str, 
                      siteName: str, 
                      siteIsProbe: bool=False, 
                      prtgUrl: Optional[str]=None, 
                      username: Optional[str]=None, 
                      password: Optional[SecretStr]=None, 
                      isPasshash: bool=False,
                      httpsVerify: bool=True):
    if prtgUrl and username and password:
        # customer PRTG instance
        prtg_instance = PrtgApi(prtgUrl, username, password.get_secret_value(), is_passhash=isPasshash, requests_verify=httpsVerify)
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH, requests_verify=httpsVerify)
    try:
        errors = compare_snow_prtg.compare(prtg_instance, companyName, siteName, siteIsProbe)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=e)
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')
    else:
        if errors:
            return f'Successfully checked company {companyName} at {siteName} with {errors} errors found. Report will be sent out momentarily.'
        elif errors == 0:
            return f'Successfully checked company {companyName} at {siteName} with {errors} errors. No report created.'
        else:
            raise HTTPException(status_code=400, detail=f'No PRTG managed devices found.')

@logger.catch
@app.put('/confirmReconcile', dependencies=[Depends(authorize)])
def confirm_reconcile(companyName: str, 
                      siteName: str, 
                      templateGroup: int, 
                      templateDevice: int, 
                      unpause: Optional[bool]=False, 
                      siteIsProbe: bool=False, 
                      prtgUrl: Optional[str]=None, 
                      username: Optional[str]=None, 
                      password: Optional[SecretStr]=None, 
                      isPasshash: bool=False,
                      httpsVerify: bool=True):
    '''**Please run _reconcileCompany_ first to see changes before confirming!**
    '''
    if prtgUrl and username and password:
        # custom PRTG instance
        prtg_instance = PrtgApi(prtgUrl, username, password.get_secret_value(), templateGroup, templateDevice, isPasshash, httpsVerify)
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, templateGroup, templateDevice, PRTG_IS_PASSHASH, httpsVerify)
    try:
        errors = update_prtg.update_company(prtg_instance, companyName, siteName, unpause, siteIsProbe)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=f'Could not find PRTG probe of {companyName} at {siteName}')
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')

@logger.catch
@app.get('/reconcileAll', dependencies=[Depends(authorize)], include_in_schema=False)
def reconcile_all(prtgUrl: Optional[str]=None, 
                  username: Optional[str]=None, 
                  password: Optional[SecretStr]=None, 
                  isPasshash: bool=False,
                  httpsVerify: bool=True):
    if prtgUrl and username and password:
        try:
            # custom PRTG instance
            prtg_instance = PrtgApi(prtgUrl, username, password.get_secret_value(), is_passhash=isPasshash, requests_verify=httpsVerify)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        # default PRTG instance
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH, requests_verify=httpsVerify)
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')
