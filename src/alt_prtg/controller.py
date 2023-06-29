from prtg import ApiClient

from alt_prtg.models import Group

class PrtgController:
    def __init__(self, client: ApiClient):
        self.client = client

    def add_group(self, group: Group):
        