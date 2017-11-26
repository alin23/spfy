__version__ = '2.4.0'
import pathlib  # isort:skip
root = pathlib.Path(__file__).parent  # isort:skip

import kick  # isort:skip
kick.start('spfy')  # isort:skip

from kick import config, logger  # isort:skip

from .result import SpotifyResult
from .client import SpotifyClient
from .wrapper import Spotify
from .constants import *
from .exceptions import *
