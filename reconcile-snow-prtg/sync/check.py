import yaml
from pathlib import PurePath

from snow.api import SnowApi
from prtg.api import PrtgApi

with open((PurePath(__file__).parent/'mapping.yaml')) as map_stream:
    mapping = yaml.safe_load(map_stream)


