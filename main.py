import configparser
import logging.handlers
from pathlib import PurePath

from fastapi import FastAPI, HTTPException
from loguru import logger

import compare_snow_prtg
from init_prtg import init_prtg_from_snow

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

@logger.catch
@app.post('/initPRTG')
def init_prtg(companyName: str, siteName: str, probeId: int):
    try:
        init_prtg_from_snow(companyName, siteName, probeId)
        return 'Successfully initialized PRTG devices from SNOW.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred ')

@logger.catch
@app.put('/reconcileCompany')
def reconcile_company(companyName: str, siteName: str):
    try:
        errors = compare_snow_prtg.compare_with_attempts(companyName, siteName)
        if errors:
            if errors == -1:
                raise HTTPException(status_code=422, detail=f'No devices found for company {companyName} at {siteName}.')
            else:
                return f'Successfully checked company {companyName} at {siteName} with {errors} errors found. Report will be sent out momentarily.'
        else:
            raise HTTPException(status_code=400, detail='An error has occurred. Failed to check.')
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check.')

@logger.catch
@app.put('/reconcileAll')
def reconcile_all():
    try:
        compare_snow_prtg.compare_all()
        return 'Successfully checked all company sites. Reports will be sent out momentarily.'
    except Exception as e:
        logger.exception(f'Exception: {e}')
        raise HTTPException(status_code=400, detail='An error has occurred. Failed to check all company sites.')