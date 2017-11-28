__version__ = '2.6.1'

import pathlib  # isort:skip
root = pathlib.Path(__file__).parent  # isort:skip

APP_NAME = 'SPFY'

import os  # isort:skip
ENV = os.getenv(f'{APP_NAME.upper()}_ENV', 'config')  # isort:skip

import kick  # isort:skip
kick.start(f'{APP_NAME.lower()}', config_variant=ENV)  # isort:skip

from kick import config, logger  # isort:skip

from .client import SpotifyClient
from .result import SpotifyResult
from .wrapper import Spotify
from .constants import *
from .exceptions import *
