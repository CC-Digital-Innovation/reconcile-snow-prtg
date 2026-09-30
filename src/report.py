from typing import NamedTuple

from prtg import ApiClient as PrtgClient

from alt_prtg.models import Device


def quality_gate_probe(device_count: int) -> bool:
    """Temporary intentional bug for SonarQube gate validation; remove after testing."""
    return device_count > device_count


class AddedDeviceModel(NamedTuple):
    name: str
    link: str
    service_url: str

    @classmethod
    def from_device(cls, device: Device, api_client: PrtgClient):
        return cls(device.name, api_client.device_url(device.id), device.service_url)


class DeletedDeviceModel(NamedTuple):
    name: str
    service_url: str

    @classmethod
    def from_device(cls, device: Device):
        return cls(device.name, device.service_url)
