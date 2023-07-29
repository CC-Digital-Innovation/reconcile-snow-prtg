from typing import BinaryIO, List, Union

import requests
from requests.auth import AuthBase


class EmailHeaderAuth(AuthBase):
    def __init__(self, key: str):
        self.key = key

    def __call__(self, r):
        r.headers['API_KEY'] = self.key
        return r

class EmailApi:
    def __init__(self, url: str, auth: AuthBase):
        self.url = url
        self.session = requests.Session()
        self.session.auth = auth

    def email(self, 
              to: str, 
              subject: str, 
              cc: Union[str, None] = None, 
              bcc: Union[str, None] = None, 
              body: Union[str, None] = None, 
              report_name: Union[str, None] = None,
              table_title: Union[List[str], None] = None,
              files: Union[List[BinaryIO], None] = None):
        url = self.url + '/emailReport/'
        data = {
            'subject': subject,
            'to': to,
            'cc': cc,
            'bcc': bcc,
            'body': body,
            'report_name': report_name,
            'table_title': table_title
        }

        response = self.session.post(url, data, files=files)
        response.raise_for_status()
        return response.json()
