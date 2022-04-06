import configparser
import logging.handlers
import sys
from pathlib import PurePath
from typing import Optional

from fastapi import FastAPI, HTTPException
from loguru import logger

import compare_snow_prtg
from init_prtg import init_prtg_from_snow
from prtg_api import PRTGInstance

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

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
    # remove default logger
    logger.remove()
    if log_level == "QUIET":
        logger.disable(__name__)
    else:
        logger.add(sys.stderr, level=log_level)
        if SYSLOG:
            logger.add(logging.handlers.SysLogHandler(address = (SYSLOG_HOST, SYSLOG_PORT)), level=log_level)

set_log_level(LOG_LEVEL)
logger.info('Starting up XSAutomate API...')
app = FastAPI()

@logger.catch
@app.post('/initPRTG')
def init_prtg(token: str, companyName: str, siteName: str, probeId: int, templateGroup: int, templateDevice: int, unpause: Optional[bool]=False, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        try:
            prtg_instance = PRTGInstance(prtgUrl, username, password, templateGroup, templateDevice, isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, templateGroup, templateDevice, PRTG_IS_PASSHASH)
    try:
        response = init_prtg_from_snow(prtg_instance, companyName, siteName, probeId, unpause)
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred')
    else:
        if response:
            raise HTTPException(status_code=400, detail=response)
        return 'Successfully initialized PRTG devices from SNOW.'

@logger.catch
@app.get('/reconcileCompany')
def reconcile_company(token: str, companyName: str, siteName: str, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        try:
            prtg_instance = PRTGInstance(prtgUrl, username, password, is_passhash=isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH)
    try:
        errors = compare_snow_prtg.compare_with_attempts(prtg_instance, companyName, siteName)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Could not find PRTG probe of {companyName} at {siteName}')
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
@app.get('/reconcileAll')
def reconcile_all(token: str, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password:
        try:
            prtg_instance = PRTGInstance(prtgUrl, username, password, is_passhash=isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(PRTG_BASE_URL, PRTG_USER, PRTG_PASSHASH, is_passhash=PRTG_IS_PASSHASH)
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')
