import logging.handlers
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from loguru import logger

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
logger.info('Starting up XSAutomate API...')
app = FastAPI()

@logger.catch
@app.post('/initPRTG')
def init_prtg_req(token: str, companyName: str, siteName: str, probeId: int, templateGroup: int, templateDevice: int, unpause: Optional[bool]=False, siteIsProbe: Optional[bool]=False, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        try:
            prtg_instance = PrtgApi(prtgUrl, username, password, templateGroup, templateDevice, isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, templateGroup, templateDevice, PRTG_IS_PASSHASH)
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
@app.get('/reconcileCompany')
def reconcile_company(token: str, companyName: str, siteName: str, siteIsProbe: Optional[bool]=False, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        prtg_instance = PrtgApi(prtgUrl, username, password, is_passhash=isPasshash)
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH)
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
@app.put('/confirmReconcile')
def confirm_reconcile(token: str, companyName: str, siteName: str, templateGroup: int, templateDevice: int, unpause: Optional[bool]=False, siteIsProbe: Optional[bool]=False, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    '''**Please run _reconcileCompany_ first to see changes before confirming!**
    '''
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        prtg_instance = PrtgApi(prtgUrl, username, password, templateGroup, templateDevice, isPasshash)
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, templateGroup, templateDevice, PRTG_IS_PASSHASH)
    try:
        errors = update_prtg.update_company(prtg_instance, companyName, siteName, unpause, siteIsProbe)
    except ObjectNotFound as e:
        raise HTTPException(status_code=404, detail=f'Could not find PRTG probe of {companyName} at {siteName}')
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=500, detail='An error has occurred. Failed to check.')

@logger.catch
@app.get('/reconcileAll')
def reconcile_all(token: str, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        try:
            prtg_instance = PrtgApi(prtgUrl, username, password, is_passhash=isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PrtgApi(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH)
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')
