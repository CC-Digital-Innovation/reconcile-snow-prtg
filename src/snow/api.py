import requests
from loguru import logger

from .exceptions import MultipleResults, NoResults

# Maximum records returned per query (no pagination is performed).
RECORD_LIMIT = 10000

# ServiceNow encoded query for active configuration items monitored by PRTG.
ACTIVE_CI_QUERY = (
    'install_status=1'              # Installed
    '^ORinstall_status=101'         # Active
    '^ORinstall_status=109'         # Duplicate Active
    '^ORinstall_status=107'         # Duplicate installed
    '^u_prtg_implementation=true'
)


def _one(records: list[dict]) -> dict:
    """Return the only record in a result, or raise if there are zero or several."""
    if not records:
        raise NoResults('No records found')
    if len(records) > 1:
        raise MultipleResults('Expected single-record result, got multiple')
    return records[0]


class ApiClient:
    def __init__(self, instance, username, password, ssl=True, timeout=60):
        self.instance = instance
        self.ssl = ssl
        self.timeout = timeout
        self._username = username
        self._password = password
        protocol = 'https' if ssl else 'http'
        self.base_url = f'{protocol}://{instance}.service-now.com'
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

    def _request(self, method, api_path, params=None, payload=None) -> list[dict]:
        """Send a request to the REST API (/api/now) and return the `result` as a list of records."""
        url = f'{self.base_url}/api/now{api_path}'
        response = self.session.request(method, url, params=params, json=payload, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()['result']
        return result if isinstance(result, list) else [result]

    def _get(self, api_path, query, display_value=False, **extra_params) -> list[dict]:
        params = {
            'sysparm_query': query,
            'sysparm_limit': RECORD_LIMIT,
            'sysparm_display_value': 'true' if display_value else 'false',
            **extra_params,
        }
        return self._request('GET', api_path, params=params)

    def get_u_category_labels(self):
        '''Returns a list of all device categories'''
        categories = self._get('/table/sys_choice', 'element=u_category')
        return sorted({category['label'] for category in categories})

    def get_u_used_for_labels(self):
        '''Returns a list of all u_used_for choices'''
        categories = self._get('/table/sys_choice', 'element=u_used_for')
        return sorted({category['label'] for category in categories})

    def get_companies(self):
        '''Returns a list of all companies'''
        return self._get('/table/core_company', 'active=true^ORDERBYname')

    def get_company_sites(self, company_name):
        '''Return all sites of a company'''
        return self._get('/table/cmn_location', f'u_active=true^company.name={company_name}')

    def get_company(self, company_name):
        '''Return a company record

        Raise
        -----
        snow.exceptions.MultipleResults
            More than one record found

        snow.exceptions.NoResults
            Could not find record
        '''
        return _one(self._get('/table/core_company', f'active=true^name={company_name}'))

    def get_location(self, location_name):
        '''Return a site location

        Raise
        -----
        snow.exceptions.MultipleResults
            More than one record found

        snow.exceptions.NoResults
            Could not find record
        '''
        return _one(self._get('/table/cmn_location', f'u_active=true^name={location_name}'))

    def get_company_locations(self, company_name):
        '''Return a list of all locations of a company'''
        query = f'u_active=true^company.name={company_name}^ORDERBYstate^ORDERBYcity'
        return self._get('/table/cmn_location', query)

    def get_ci(self, ci_id: str):
        records = self._get('/table/cmdb_ci', f'sys_id={ci_id}', display_value=True)
        if not records:
            raise NoResults(f'No results found for sys_id {ci_id}.')
        return records[0]

    def get_cis_filtered(self, company_name, location_name, category, stage):
        '''Returns a list of all devices filtered by company, location, and category'''
        query = (
            f'{ACTIVE_CI_QUERY}'
            f'^company.name={company_name}'
            f'^location.name={location_name}'
            f'^u_category={category}'
            f'^u_used_for={stage}'
            '^u_prtg_instrumentation=false'
            '^ORDERBYname'
        )
        return self._get('/table/cmdb_ci', query)

    def get_cis_by_site(self, company_name, location_name, internal = None, missing = False):
        """Returns a list of all configuration items from a company site

        Args:
            company_name (str): company name to filter by
            location_name (str): location name to filter by
            internal (bool, optional): further filter by internal value. Defaults to None.
            missing (bool, optional): further filter for missing PRTG ID. Defaults to False.

        Returns:
            list[dict]: list of configuration item details
        """
        query = f'{ACTIVE_CI_QUERY}^company.name={company_name}^location.name={location_name}^ORDERBYname'

        if internal is not None:
            if internal:
                query += '^u_prtg_instrumentation=true'
            else:
                query += '^u_prtg_instrumentation=false^ORu_prtg_instrumentationISEMPTY'

        if missing:
            query += '^u_prtg_idISEMPTY'

        return self._get('/table/cmdb_ci', query, display_value=True)

    def get_record(self, link):
        with requests.Session() as s:
            s.auth = (self._username, self._password)
            response = s.get(link)
        return response.json()

    def ci_url(self, sys_id):
        protocol = 'https' if self.ssl else 'http'
        return f'{protocol}://{self.instance}.service-now.com/cmdb_ci?sys_id={sys_id}'

    def update_prtg_id(self, sys_id, value):
        updated = self._request('PUT', f'/table/cmdb_ci/{sys_id}', payload={'u_prtg_id': value})[0]
        return updated['u_prtg_id'] == value

    def get_cis_count(self, company_name, location_name):
        """Get a count of all PRTG monitored configuration items from a company
        site."""
        query = f'{ACTIVE_CI_QUERY}^company.name={company_name}^location.name={location_name}^ORDERBYname'
        response = self._get('/stats/cmdb_ci', query, sysparm_count='true')[0]
        return int(response['stats']['count'])

    def post_log(self, request_id, state, response_msg):
        protocol = 'https' if self.ssl else 'http'
        url = f'{protocol}://{self.instance}.service-now.com/api/fuss2/prtg_outbound/log'
        auth = (self._username, self._password)
        body = {
            'request_id': request_id,
            'state': state,
            'response_msg': response_msg
        }
        response = requests.post(url, json=body, auth=auth)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            # log unhandled errors and reraise
            logger.error(e)
            logger.error(f'Response text: {response.text}')
            raise e
        return response.json()
