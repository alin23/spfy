__version__ = '2.6.0'

import pathlib  # isort:skip
root = pathlib.Path(__file__).parent  # isort:skip

import os  # isort:skip
ENV = os.getenv('SPFY_ENV', 'config')  # isort:skip

import kick  # isort:skip
kick.start('spfy', config_variant=ENV)  # isort:skip

from kick import config, logger  # isort:skip

from .client import SpotifyClient
from .result import SpotifyResult
from .wrapper import Spotify
from .constants import *
from .exceptions import *
