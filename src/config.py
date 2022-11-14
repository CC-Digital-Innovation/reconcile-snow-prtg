import configparser
from pathlib import PurePath

_curr_file = PurePath(__file__)

# load config file
config = configparser.ConfigParser()
config.read(_curr_file.with_name('config.ini'))
