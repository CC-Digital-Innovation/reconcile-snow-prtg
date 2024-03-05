from fastapi import FastAPI
from fastapi import FastAPI, Security, HTTPException, status
import uvicorn
import urllib3
from fastapi.security import APIKeyHeader
import requests
import dotenv
import os
import json
import os
import ssl
from prtg import ApiClient
from prtg.auth import BasicToken
from datetime import datetime
from pytz import timezone
# Disable SSL Warnings for requests
urllib3.disable_warnings()
ssl._create_default_https_context = ssl._create_unverified_context

# Define FastAPI App
desc = "Platform to sync device details in snow to prtg"

tag_device_info = "Device Info"

tag_device_updates = "Device Updates"

app = FastAPI(
    title = "SNOW and PRTG Sync API",
    version = "0.0.1",
    description= desc
)
api_key_header = APIKeyHeader(name = 'X-API_KEY')

dotenv.load_dotenv()
nocodb_url = os.getenv("nocodb_url")
xc_auth = os.getenv("nocodb_xcauth")

def get_nocodb_data():
    headers = {
        'xc-token': xc_auth
    }
    response = requests.get(nocodb_url, headers=headers)
    if response.status_code != 200:
        return {"error": "Error getting NocoDB data"}
    else:
        return response.text

# Parse the local NocoDB data
def get_parsed_nocodb_data(data):
    try:
        data = json.loads(data)
        envvariable_names = []
        envvariable_values = []
        for i in data["list"]:
            if i["enviornment variables"] != None:
                envvariable_names.append(i["enviornment variables"])
            if i["values"] != None:
                envvariable_values.append(i["values"])
        return envvariable_names, envvariable_values
    except:
        return {"error": "Error parsing NocoDB data"}

# Structure the enviornment variables from the local nocodb table into a dictionary
def get_allenv_variables():
    env_names, env_values = get_parsed_nocodb_data(get_nocodb_data())
    # Make a dictionary of each env_name to env_value
    env_dict = {}
    for i in range(len(env_names)):
        env_dict[env_names[i]] = env_values[i]
    return env_dict

# Load NocDB env variables
config = get_allenv_variables()

prtg_url = config["prtg_url"]
prtg_key = config["prtg_key"]
fastapi_password = config["password"]
fastapi_certfile = config["certfile"]
fastapi_keyfile = config["keyfile"]
host = config["host"]
port = config["port"]
api_keys = [fastapi_password]

auth = BasicToken(prtg_key)
ssl._create_default_https_context = ssl._create_unverified_context
client = ApiClient(f'https://{prtg_url}', auth, requests_verify=False)

# name, host, location, inactive-->remove from prtg, active devices
# sync script already made
# code doesnt handel moving devices around
# endpoint to move devices to a different group

api_function = '/api/table.xml'
# prtg_api_url = f"https://{prtg_url}/api/table.xml?content=sensors&columns=sensor&apitoken={prtg_key}"
prtg_api_url1 = f"https://{prtg_url}/api/table.json?content=devices&columns=objid,name,active,status,probe,group,host,priority,tags,location,parentid,icon&count=*&apitoken={prtg_key}"
prtg_api_url3 = f"https://{prtg_url}/api/table.json?content=groups&columns=objid,name,active,status,probe,group,host,priority,tags,location,parentid,icon&count=*&apitoken={prtg_key}"
# prtg_api_url2 = f"https://{prtg_url}/api/table.json?content=devices&columns=objid,device&count=*&apitoken={prtg_key}" 
# Make the GET request
def get_api_key(api_key_header: str = Security(api_key_header)) -> str:
    if api_key_header in api_keys:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API Key",
    )

# Device to rename in snow
# prtg_api_url2 =

# @app.get("/get_device_info", tags= ['Device Info'])
# async def get_device_info(api_key: str = Security(get_api_key)):
#     response = requests.get(prtg_api_url1, verify=False)
    
#     return response.json()

@app.get("/get_all_devices", tags= [tag_device_info])
async def get_all_devices(api_key: str = Security(get_api_key)):
    get_devices = client.get_all_devices()
    return get_devices

@app.get("/get_all_groups", tags= [tag_device_info])
async def get_group_info(api_key: str = Security(get_api_key)):
    get_groups = client.get_all_groups()
    return get_groups

# Test PASSED ("2024-03-05 09:28:40 AM")
@app.post("/move_device_groups", tags= [tag_device_updates])
async def move_device_groups(objid : int, 
                            new_group_objid : int,
                            api_key: str = Security(get_api_key)):
    
    try:
        device = client.get_device(objid)
        group = client.get_group(new_group_objid)
        
        # Get the current time in PST and format it well with the time abbreviation at and import necessary modules
        timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")

        # Move the device to the new group
        response = requests.post(f"https://{prtg_url}/api/moveobject.htm?id={objid}&targetid={new_group_objid}&apitoken={prtg_key}", verify=False)

        # Get the name of the objid and the new_group_objid
        # If the device was moved successfully, return a message saying so
        if response.status_code == 200:
            return_message = {
                "message": f"Device moved successfully",
                "timestamp" : timestamp,
                "device_name" : device['name'],
                "old_group_name" : device['group'],
                "new_group_name" : group['name'],
                "objid" : objid,
                "new_group_objid" : new_group_objid,
            }
        # If the device was not moved successfully, return a message saying so
            return return_message
    except Exception as e:
        return {"error": f"Device was not moved successfully{e}"}

# Test PASSED (2024-03-05 09:33:45 AM)
@app.post("/move_group_to_group", tags= [tag_device_updates])
async def move_group_to_group(groupid : int, 
                            new_group_objid : int,
                            api_key: str = Security(get_api_key)):
    try:
        timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")

        group = client.get_group(groupid)
        new_group = client.get_group(new_group_objid)

        response = requests.post(f"https://{prtg_url}/api/moveobject.htm?id={groupid}&targetid={new_group_objid}&apitoken={prtg_key}", verify=False)

        if response.status_code == 200:
            return_message = {
                "message": f"Group moved successfully",
                "groupid" : groupid,
                "old_group_name" : group["name"],
                "new_group_name" : new_group["name"],
                "timestamp" : timestamp,
            }
        return return_message
    except Exception as e:
        return {"error": f"Group was not moved successfully{e}"}

# Set a device property

# Rename a device
# Test PASSED (2024-03-05 09:35:30 AM)
@app.post("/rename_group", tags= [tag_device_updates])
async def rename_group(objid: int, 
                        value : str,
                        api_key: str = Security(get_api_key)):
    try:
        # Set the device property
        timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")
        group = client.get_group(objid)
        response = requests.post(f'https://{prtg_url}/api/rename.htm?id={objid}&value={value}&apitoken={prtg_key}', verify=False)

        if response.status_code == 200:
            return_message = {
                "message": f"Group renamed successfully",
                "timestamp" : timestamp,
                "old_group_name" : group['name'],
                "new_group_name" : value,
                "objid" : objid,
            }
            return return_message
    except Exception as e:
        return {"error": f"Group was not renamed successfully{e}"}

# Rename a device
# Test PASSED (2024-03-05 09:37:06 AM)
@app.post("/rename_device", tags= [tag_device_updates])
async def rename_device(objid: int, 
                        value : str,
                        api_key: str = Security(get_api_key)):
    try:
        # Set the device property
        timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")
        device = client.get_device(objid)
        response = requests.post(f'https://{prtg_url}/api/rename.htm?id={objid}&value={value}&apitoken={prtg_key}', verify=False)
        if response.status_code == 200:
            return_message = {
                "message": f"Device renamed successfully",
                "timestamp" : timestamp,
                "old_device_name" : device['name'],
                "new_device_name" : value,
                "objid" : objid,
            }
            return return_message
    except Exception as e:
        return {"error": f"Device was not renamed successfully{e}"}

# Set the location of a device
# Test PASSED (2024-03-05 10:04:25 AM)
@app.post("/set_device_location", tags= [tag_device_updates])
async def set_device_location(objid: int,
                              location: str,
                              api_key: str = Security(get_api_key)):
    try:
        # Set the obj property base
        # In order to set a location, you must turn off inherit location
        device = client.get_device(objid)
        timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")
        # Turn off inherit location
        response_loc_off = requests.post(f"https://{prtg_url}/api/setobjectproperty.htm?id={objid}&name=locationgroup_&value=0&apitoken={prtg_key}", verify=False)

        # Set the location")
        response_loc_set = requests.post(f'https://{prtg_url}/api/setobjectproperty.htm?id={objid}&name=location&value={location}&apitoken={prtg_key}', verify=False)

        return_message = {
            "message" : "Device location set, and inherit location turned off",
            "timestamp" : timestamp,
            "device_name" : device['name'],
            "objid" : objid,
            "device_location_raw" : device['location_raw'],          
        }
        return return_message
    except Exception as e:
        return {"error": f"Device location was not set successfully{e}"}

# Odd bug with groups, the location is being set but does not show up when I call the groups endpoint
# Groups can't have locations, But the devices in those groups can inherit the location of the group if it is turned on
# Test PASSED (2024-03-05 10:26:59 AM)
@app.post("/set_group_location", tags= [tag_device_updates])
async def set_group_location(objid: int,
                            location: str,
                            api_key: str = Security(get_api_key)):
        try:
            # Set the obj property base
            # In order to set a location, you must turn off inherit location
            group = client.get_group(objid)
            timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")
            # Turn off inherit location
            response_loc_off = requests.post(f"https://{prtg_url}/api/setobjectproperty.htm?id={objid}&name=locationgroup_&value=0&apitoken={prtg_key}", verify=False)

            # Set the location")
            response_loc_set = requests.post(f'https://{prtg_url}/api/setobjectproperty.htm?id={objid}&name=location&value={location}&apitoken={prtg_key}', verify=False)
    
            return_message = {
                "message" : "Group location set, and inherit location turned off for group",
                "timestamp" : timestamp,
                "group_name" : group['name'],
                "objid" : objid,

            }
            return return_message
        except Exception as e:
            return {"error": f"Group location was not set successfully{e}"}

# Set the hostname of a device
# Test PASSED (2024-03-05 10:50:27 AM)
@app.post("/set_device_host", tags= [tag_device_updates])
async def set_device_hostname(objid: int,
                              host: str,
                              api_key: str = Security(get_api_key)):
        try:
            timestamp = datetime.now(timezone('US/Pacific')).strftime("%Y-%m-%d %I:%M:%S %p")

            # Set the hostname property
            response = requests.post(f'https://{prtg_url}/api/setobjectproperty.htm?id={objid}&name=host&value={host}&apitoken={prtg_key}', verify=False)
            device = client.get_device(objid)
            return_message = {
                "message" : "Device hostname set",
                "timestamp" : timestamp,
                "device_name" : device['name'],
                "objid" : objid,
                "device_host" : device['host'],
            }
            return return_message
        except Exception as e:
            return {"error": f"Device host was not set successfully{e}"}



if __name__ == "__main__":
    uvicorn.run(app = "prtg_snow:app",
                host = host, 
                port = int(port), 
                ssl_version = ssl.PROTOCOL_TLSv1_2, 
                ssl_certfile = fastapi_certfile, 
                ssl_keyfile = fastapi_keyfile,
                log_level = "info",
                reload= True)