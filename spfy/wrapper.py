#!/usr/bin/env python3
import fire
from pony.orm import db_session

import kick

from . import APP_NAME, config, logger
from .client import SpotifyClient
from .mixins import PlayerMixin, RecommenderMixin


class Spotify(SpotifyClient, PlayerMixin, RecommenderMixin):
    """Spotify high-level wrapper."""
    cli = False

    def __init__(self, *args, email=None, username=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email or config.auth.email
        self.username = username or config.auth.username

    def auth(self, email=config.auth.email, username=config.auth.username):
        if self.cli and not self.is_authenticated:
            try:
                self.authenticate(email=email, username=username)
            except Exception as exc:
                logger.exception(exc)
        return self

    def __dir__(self):
        names = super().__dir__()
        names = [name for name in names if not name.startswith("_") and name != "user"]
        return names

    @staticmethod
    def update_config(name="config"):
        kick.update_config(APP_NAME.lower(), variant=name)


def main():
    """Main function."""
    try:
        Spotify.cli = True
        with db_session:
            fire.Fire(Spotify)
    except KeyboardInterrupt:
        print("Quitting")


if __name__ == "__main__":
    main()
