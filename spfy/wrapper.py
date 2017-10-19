#!/usr/bin/env python3
import fire

from . import config
from .client import SpotifyClient
from .mixins import PlayerMixin, ServerMixin, RecommenderMixin


class Spotify(SpotifyClient, PlayerMixin, RecommenderMixin, ServerMixin):
    """Spotify high-level wrapper."""
    cli = False

    def __init__(self, email=None, username=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email or config.auth.email
        self.username = username or config.auth.username
        if self.cli and not self.is_authenticated:
            self.authenticate(email=self.email, username=self.username)

    def __dir__(self):
        names = super().__dir__()
        names = [name for name in names if not name.startswith('_') and name != 'user']
        return names


def main():
    """Main function."""

    try:
        Spotify.cli = True
        fire.Fire(Spotify)
    except KeyboardInterrupt:
        print('Quitting')


if __name__ == '__main__':
    main()
