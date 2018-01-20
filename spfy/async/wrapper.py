#!/usr/bin/env python3
import sys

from pony.orm import db_session

import fire
import kick

from .. import APP_NAME, config
from .client import SpotifyClient
from ..mixins.async import PlayerMixin, RecommenderMixin


# pylint: disable=too-many-ancestors
class Spotify(SpotifyClient, PlayerMixin, RecommenderMixin):
    """Spotify high-level wrapper."""
    cli = False
    loop = None

    def __init__(self, *args, email=None, username=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email or config.auth.email
        self.username = username or config.auth.username

    def __dir__(self):
        names = super().__dir__()
        names = [name for name in names if not name.startswith('_') and name != 'user']
        return names

    async def auth(self, email=None, username=None):
        if self.cli and not self.is_authenticated:
            await self.authenticate(email=email, username=username)
        return self

    @staticmethod
    def update_config(name='config'):
        kick.update_config(APP_NAME.lower(), variant=name)


def main():
    """Main function."""

    import asyncio
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    try:
        Spotify.cli = True
        Spotify.loop = asyncio.get_event_loop()
        spotify = Spotify()
        with db_session:
            fire.Fire(spotify)
    except KeyboardInterrupt:
        print('Quitting')
    finally:
        if spotify.session:
            Spotify.loop.run_until_complete(spotify.session.__aexit__(*sys.exc_info()))


if __name__ == '__main__':
    main()
