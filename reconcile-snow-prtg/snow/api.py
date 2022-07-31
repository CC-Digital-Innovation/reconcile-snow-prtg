import pysnow
import requests

from config import config

BASE_URL = config['snow']['base_url']
API_USER = config['snow']['api_user']
API_PASS = config['snow']['api_password']
API_KEY = config['snow']['api_key']

class SnowApi:
    def __init__(self, instance, username, password):
        self.client = pysnow.Client(instance, user=username, password=password)

    def (self, ):


    def get_choice_labels(self, choice):
        choice_table = self.client.resource(api_path='/table/sys_choice')
        choices = choice_table.get(query={'element': choice})
        return sorted({choice['label']} for choice in choices.all())

    def ci_url(sys_id):
        return f'{BASE_URL}/cmdb_ci?sys_id={sys_id}'

    def get_record(link):
        with requests.Session() as s:
            s.auth = (API_USER, API_PASS)
            response = s.get(link)
        return response.json()
