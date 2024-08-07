from typing import IO

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
              cc: str | None = None,
              bcc: str | None = None,
              body: str | None = None,
              report_name: str | None = None,
              table_title: list[str] | None = None,
              files: list[tuple[str, IO[bytes]]] | None = None):
        data = {
            'subject': subject,
            'to': to,
            'cc': cc,
            'bcc': bcc,
            'body': body,
            'report_name': report_name,
            'table_title': table_title
        }
        formatted_files = []
        if files is not None:
            for file in files:
                formatted_files.append(('files', file))
        else:
            formatted_files = None

        response = self.session.post(self.url, data, files=formatted_files)
        response.raise_for_status()
        return response.json()
