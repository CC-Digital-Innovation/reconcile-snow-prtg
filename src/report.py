from dataclasses import dataclass

from prtg import ApiClient as PrtgClient

from alt_prtg.models import Device


@dataclass
class AddedDeviceModel:
    name: str
    link: str
    service_url: str

def get_add_device_model(device: Device, api_client: PrtgClient):
    return AddedDeviceModel(device.name, api_client.device_url(device.id), device.service_url)
