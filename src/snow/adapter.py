from prtg import Icon

from .models import ConfigItem
from alt_prtg.models import Device, Status

class PrtgDeviceAdapter(Device):
    def __init__(self, ci: ConfigItem):
        try:
            name = '{} {} ({})'.format(ci.manufacturer.name, ci.model_number, ci.ip_address)
        except AttributeError:
            raise ValueError(f'Configuration item "{ci.name}" is missing required attribute manufacturer.')
        
        # Replace whitespaces with dash becauese PRTG tags are separated by whitespaces
        tags = [ci.stage, ci.category.replace(' ', '-')]
        
        if ci.ip_address is None:
            raise ValueError(f'Configuration item "{ci.name}" is missing required attribute IP address.')

        try:
            icon = Icon[ci.manufacturer.name.upper()]
        except KeyError:
            icon = None
        super(PrtgDeviceAdapter, self).__init__(ci.prtg_id, name, str(ci.ip_address), ci.link, 3, tags, '', icon, Status.UP, True)
