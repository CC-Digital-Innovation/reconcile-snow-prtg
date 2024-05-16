from ipaddress import AddressValueError, IPv4Address

from .models import Company, ConfigItem, Country, Location, Manufacturer


class SnowController:
    def __init__(self, client):
        self.client = client

    def get_company_by_name(self, name: str) -> Company:
        company = self.client.get_company(name)

        # map SNOW choice list names to formats
        format_map = {
            'ip only': '{manufacturer.name} {model_number} ({ip_address})',
            'hostname + ip': '{manufacturer.name} {model_number} {host_name} ({ip_address})'
        }

        return Company(company['sys_id'], company['name'].strip(), company['u_abbreviated_name'], format_map.get(company['u_prtg_format'].lower(), None))

    def _get_location(self, location: dict):
        try:
            response = self.client.get_record(location['u_country']['link'])
        except TypeError:
            country = None
        else:
            country = Country(response['result']['sys_id'], response['result']['name'])
        street = location['street'].replace('\r\n', ' ')
        return Location(location['sys_id'], location['name'].strip(), country, street, location['city'], location['state'])

    def get_location_by_name(self, name: str) -> Location:
        location = self.client.get_location(name)
        return self._get_location(location)

    def get_company_locations(self, company_name: str) -> list[Location]:
        locations = self.client.get_company_locations(company_name)
        return [self._get_location(location) for location in locations]

    def _get_config_item(self, ci: dict):
        try:
            ip_address = IPv4Address(ci['ip_address'].strip())
        except AddressValueError:
            ip_address = None

        hostname = ci['u_host_name']

        try:
            response = self.client.get_record(ci['manufacturer']['link'])
        except TypeError:
            manufacturer = None
        else:
            manufacturer = Manufacturer(response['result']['sys_id'], response['result']['name'])

        stage = ci['u_used_for'] if ci['u_used_for'] is not None else ''
        category = ci['u_category'] if ci['u_category'] is not None else ''
        sys_class = ci['sys_class_name'] if ci['sys_class_name'] is not None else ''

        link = self.client.ci_url(ci['sys_id'])

        try:
            prtg_id = int(ci['u_prtg_id'])
        except ValueError:
            prtg_id = None

        cc_device = True if ci['u_prtg_instrumentation'] == 'true' else False
        return ConfigItem(ci['sys_id'], ci['name'], ip_address, manufacturer,
                          ci['model_number'], stage, category, sys_class, link,
                          prtg_id, cc_device, hostname)

    def get_config_items(self, company: Company, location: Location) -> list[ConfigItem]:
        cis = self.client.get_cis_by_site(company.name, location.name)
        return [self._get_config_item(ci) for ci in cis]

    def update_config_item(self, ci: ConfigItem):
        # Currently only updates prtg_id field
        self.client.update_prtg_id(ci.id, ci.prtg_id)

    def get_device_count(self, company: Company, location: Location) -> int:
        return self.client.get_cis_count(company.name, location.name)
