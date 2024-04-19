// Define the variables for objid and host
const objid_bind = '2062';
const host_bind = '127.0.0.1:8000';
const hostname_bind = 'examplehost.host.com';
const ip_bind = '121.1.1.1';
const manufactuer_model_bind = 'Dell Isilon 2200';
const manufacturer_number_bind = '2234';
const location_bind = 'San Diego, CA';

const category_bind =  'Hardware'; 

const used_for_bind = 'Q/A';

const prtg_url_bind = 'joyful-moose.my-prtg.com';
const prtg_api_key_bind = 'H6U4BA7L5MUVVAM6C74SVYDP3W3QBGPKQX4R2TLIG4======';
const min_devices_bind = 0; 
                            //

// Define the parameters as a dictionary (object)
const params = {
  prtg_url: prtg_url_bind, // Example URL
  prtg_api_key: prtg_api_key_bind, // Example key
  objid: objid_bind, 
  hostname: hostname_bind,
  ip: ip_bind,
  manufactuer_model: manufactuer_model_bind,
  manufacturer_number: manufacturer_number_bind,
  location: location_bind,

  // Snow Category
  category: category_bind,
  // Snow Used For
  used_for: used_for_bind,

  min_devices: min_devices_bind 
};

const endpointUrl = `http://${host_bind}/sync_device`;

// Define the headers for the request
const headers = new Headers({
  'Accept': 'application/json',
  'Content-Type': 'application/json' // Set the content type to JSON
});

// Define the options for the fetch request
const requestOptions = {
  method: 'POST', 
  headers: headers,
  body: JSON.stringify(params) 
};

// Send the fetch request
fetch(endpointUrl, requestOptions)
  .then(response => {
    if (!response.ok) {
      throw new Error('Network response was not ok');
    }
    return response.json();
  })
  .then(data => {
    // Handle the JSON response data
    console.log('Response:', data);
  })
  .catch(error => {
    // Handle any errors that occurred during the fetch request
    console.error('Error:', error);
  });