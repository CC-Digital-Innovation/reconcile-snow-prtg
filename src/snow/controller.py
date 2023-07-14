from ipaddress import AddressValueError, IPv4Address
from typing import Dict, List

from .models import Country, Company, ConfigItem, Location, Manufacturer

class SnowController:
    def __init__(self, client):
        self.client = client

    def get_company_by_name(self, name: str) -> Company:
        company = self.client.get_company(name)
        return Company(company['sys_id'], company['name'].strip())
    
    def get_location_by_name(self, name: str) -> Location:
        location = self.client.get_location(name)
        try:
            response = self.client.get_record(location['u_country']['link'])
        except TypeError:
            country = None
        else:
            country = Country(response['result']['sys_id'], response['result']['name'])
        street = location['street'].replace('\r\n', ' ')
        return Location(location['sys_id'], location['name'].strip(), country, street, location['city'], location['state'])

    def _get_config_item(self, ci: Dict):
        try:
            response = self.client.get_record(ci['manufacturer']['link'])
        except TypeError:
            manufacturer = None
        else:
            manufacturer = Manufacturer(response['result']['sys_id'], response['result']['name'])
        
        try:
            ip_address = IPv4Address(ci['ip_address'])
        except AddressValueError:
            ip_address = None

        try:
            prtg_id = int(ci['u_prtg_id'])
        except ValueError:
            prtg_id = None

        link = self.client.ci_url(ci['sys_id'])
        return ConfigItem(ci['sys_id'], ci['name'], ip_address, manufacturer, ci['model_number'], ci['u_used_for'], ci['u_category'], link, prtg_id)

    def get_interal_config_items(self, company: Company, location: Location) -> List[ConfigItem]:
        internal_cis = self.client.get_internal_cis_by_site(company.name, location.name)
        return [self._get_config_item(ci) for ci in internal_cis]

    def get_config_items(self, company: Company, location: Location):
        cis = self.client.get_customer_cis_by_site(company.name, location.name)
        return [self._get_config_item(ci) for ci in cis]
