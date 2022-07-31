import configparser
from pathlib import PurePath

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)
