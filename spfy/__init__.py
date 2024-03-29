__version__ = "3.10.0"

import pathlib  # isort:skip

root = pathlib.Path(__file__).parent  # isort:skip
APP_NAME = "SPFY"

import os  # isort:skip

import kick  # isort:skip

kick.start(APP_NAME.lower())  # isort:skip

from kick import config, logger  # isort:skip

Unsplash = None
if config.unsplash.auth.client_id:
    from unsplash import Api, Auth

    auth = Auth(**config.unsplash.auth)
    Unsplash = Api(auth)
from .client import SpotifyClient
from .constants import *
from .exceptions import *
from .result import SpotifyResult
from .wrapper import Spotify
