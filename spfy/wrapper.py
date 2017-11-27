#!/usr/bin/env python3
import asyncio

import fire
import kick

from . import APP_NAME, config
from .client import SpotifyClient
from .mixins import PlayerMixin, RecommenderMixin


class Spotify(SpotifyClient, PlayerMixin, RecommenderMixin):
    """Spotify high-level wrapper."""
    cli = False

    def __init__(self, email=None, username=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loop = asyncio.get_event_loop()
        self.email = email or config.auth.email
        self.username = username or config.auth.username
        if self.cli and not self.is_authenticated:
            self.authenticate(email=self.email, username=self.username)

    def __dir__(self):
        names = super().__dir__()
        names = [name for name in names if not name.startswith('_') and name != 'user']
        return names

    def update_config(self, name='config'):
        kick.update_config(APP_NAME.lower(), variant=name)


def main():
    """Main function."""

    try:
        Spotify.cli = True
        fire.Fire(Spotify)
    except KeyboardInterrupt:
        print('Quitting')


if __name__ == '__main__':
    main()
