import pysnow
import requests


class ApiClient:
    def __init__(self, instance, username, password, ssl=True):
        self.instance = instance
        self.ssl = ssl
        self._username = username
        self._password = password
        self.client = pysnow.Client(instance=instance, user=username, password=password, use_ssl=ssl)

    def get_u_category_labels(self):
        '''Returns a list of all device categories'''
        choices = self.client.resource(api_path='/table/sys_choice')
        categories = choices.get(query={'element': 'u_category'})
        return sorted({category['label'] for category in categories.all()})

    def get_u_used_for_labels(self):
        '''Returns a list of all u_used_for choices'''
        choices = self.client.resource(api_path='/table/sys_choice')
        categories = choices.get(query={'element': 'u_used_for'})
        return sorted({category['label'] for category in categories.all()})

    def get_companies(self):
        '''Returns a list of all companies'''
        companies = self.client.resource(api_path='/table/core_company')
        query = (
            pysnow.QueryBuilder()
            .field('active').equals('true')
            .AND().field('name').order_ascending()
        )
        response = companies.get(query=query)
        return response.all()

    def get_company_sites(self, company_name):
        '''Return all sites of a company'''
        sites = self.client.resource(api_path='/table/cmn_location')
        #TODO use u_site_name when it is consistent (instead of 'name' field)
        query = (
            pysnow.QueryBuilder()
            .field('u_active').equals('true')
            .AND().field('company.name').equals(company_name)
        )
        response = sites.get(query=query)
        return response.all()

    def get_company(self, company_name):
        '''Return a company record
        
        Raise
        -----
        pysnow.exceptions.MultipleResults
            More than one record found

        pysnow.exceptions.NoResults
            Could not find record
        '''
        companies = self.client.resource(api_path='/table/core_company')
        query = (
            pysnow.QueryBuilder()
            .field('active').equals('true')
            .AND().field('name').equals(company_name)
        )
        response = companies.get(query=query, stream=True)
        return response.one()

    def get_location(self, site_name):
        '''Return a site location
        
        Raise
        -----
        pysnow.exceptions.MultipleResults
            More than one record found

        pysnow.exceptions.NoResults
            Could not find record
        '''
        locations = self.client.resource(api_path='/table/cmn_location')
        #TODO use u_site_name when it is consistent (instead of 'name' field)
        query = (
            pysnow.QueryBuilder()
            .field('u_active').equals('true')
            .AND().field('name').equals(site_name)
        )
        response = locations.get(query=query, stream=True)
        return response.one()

    def get_company_locations(self, company_name):
        '''Return a list of all locations of a company'''
        locations = self.client.resource(api_path='/table/cmn_location')
        query = (
            pysnow.QueryBuilder()
            .field('u_active').equals('true')
            .AND().field('company.name').equals(company_name)
            .AND().field('state').order_ascending()
            .AND().field('city').order_ascending()
        )
        response = locations.get(query=query)
        return response.all()

    def get_cis_filtered(self, company_name, location, category, stage):
        '''Returns a list of all devices filtered by company, location, and category'''
        cis = self.client.resource(api_path='/table/cmdb_ci')
        query = (
            pysnow.QueryBuilder()
            .field('company.name').equals(company_name)
            .AND().field('name').order_ascending()
            .AND().field('install_status').equals('1')      # Installed
            .OR().field('install_status').equals('101')     # Active
            .OR().field('install_status').equals('107')     # Duplicate installed
            .AND().field('location.name').equals(location)
            .AND().field('u_category').equals(category)
            .AND().field('u_used_for').equals(stage)
            .AND().field('u_cc_type').equals('root')
            .AND().field('u_prtg_instrumentation').equals('false')
        )
        response = cis.get(query=query)
        return response.all()

    def get_cis_by_site(self, company_name, site_name):
        '''Returns a list of all devices from a company'''
        cis = self.client.resource(api_path='/table/cmdb_ci')
        cis.parameters.display_value = True
        query = (
            pysnow.QueryBuilder()
            .field('company.name').equals(company_name)
            .AND().field('name').order_ascending()
            .AND().field('install_status').equals('1')      # Installed
            .OR().field('install_status').equals('101')     # Active
            .OR().field('install_status').equals('107')     # Duplicate installed
            .AND().field('location.name').equals(site_name)
            .AND().field('u_cc_type').equals('root')
            .OR().field('u_cc_type').is_empty()
        )
        response = cis.get(query=query)
        return response.all()

    def get_internal_cis_by_site(self, company_name, site_name):
        '''Returns a list of all interal devices to monitor for a company'''
        cis = self.client.resource(api_path='/table/cmdb_ci')
        cis.parameters.display_value = True
        query = (
            pysnow.QueryBuilder()
            .field('company.name').equals(company_name)
            .AND().field('name').order_ascending()
            .AND().field('install_status').equals('1')      # Installed
            .OR().field('install_status').equals('101')     # Active
            .OR().field('install_status').equals('107')     # Duplicate installed
            .AND().field('location.name').equals(site_name)
            .AND().field('u_cc_type').equals('root')
            .AND().field('u_prtg_instrumentation').equals('true')
        )
        response = cis.get(query=query)
        return response.all()

    def get_customer_cis_by_site(self, company_name, site_name):
        '''Returns a list of all customer devices for a company'''
        cis = self.client.resource(api_path='/table/cmdb_ci')
        cis.parameters.display_value = True
        query = (
            pysnow.QueryBuilder()
            .field('company.name').equals(company_name)
            .AND().field('name').order_ascending()
            .AND().field('install_status').equals('1')      # Installed
            .OR().field('install_status').equals('101')     # Active
            .OR().field('install_status').equals('107')     # Duplicate installed
            .AND().field('location.name').equals(site_name)
            .AND().field('u_cc_type').equals('root')
            .AND().field('u_prtg_instrumentation').equals('false')
        )
        response = cis.get(query=query)
        return response.all()

    def get_record(self, link):
        with requests.Session() as s:
            s.auth = (self._username, self._password)
            response = s.get(link)
        return response.json()

    def ci_url(self, sys_id):
        protocol = 'https' if self.ssl else 'http'
        return f'{protocol}://{self.instance}.service-now.com/cmdb_ci?sys_id={sys_id}'

    def update_prtg_id(self, sys_id, value):
        update = {'u_prtg_id': value}
        ci_table = self.client.resource(api_path='/table/cmdb_ci')
        response = ci_table.update(query={'sys_id': sys_id}, payload=update)
        return response['u_prtg_id'] == value
