import configparser
import logging.handlers
from pathlib import PurePath
from typing import Optional

from fastapi import FastAPI, HTTPException
from loguru import logger

import compare_snow_prtg
from init_prtg import init_prtg_from_snow
from prtg_api import PRTGInstance

def set_log_level(log_level):
    # Log to syslog
    # handler = logging.handlers.SysLogHandler(
    #     address=(config["local"]["sys_log_host"], config["local"].getint("sys_log_port")))
    # logger.add(handler)
    if log_level == "QUIET":
        logger.disable(__name__)

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

set_log_level(config['local']['log_level'])
logger.info('Starting up SNOW and PRTG Automation FastAPI...')
app = FastAPI()

TOKEN = config['local']['token']

@logger.catch
@app.post('/initPRTG')
def init_prtg(token: str, companyName: str, siteName: str, probeId: int, unpause: Optional[bool]=False, prtgUrl: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, isPasshash: Optional[bool]=False, templateGroup: Optional[int]=None, templateDevice: Optional[int]=None):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail='Unauthorized request.')
    if prtgUrl and username and password and templateGroup and templateDevice:
        try:
            prtg_instance = PRTGInstance(prtgUrl, username, password, templateGroup, templateDevice, isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(config['prtg']['base_url'], config['prtg']['username'], config['prtg']['passhash'], config['prtg']['template_group'], config['prtg']['template_device'], True)
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
            prtg_instance = PRTGInstance(prtgUrl, username, password, None, None, isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(config['prtg']['base_url'], config['prtg']['username'], config['prtg']['passhash'], config['prtg']['template_group'], config['prtg']['template_device'], True)
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
            prtg_instance = PRTGInstance(prtgUrl, username, password, None, None, isPasshash)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    else:
        logger.info('No parameters for a PRTG instance. Using default instance from config.')
        prtg_instance = PRTGInstance(config['prtg']['base_url'], config['prtg']['username'], config['prtg']['passhash'], config['prtg']['template_group'], config['prtg']['template_device'], True)
    try:
        compare_snow_prtg.compare_all(prtg_instance)
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')