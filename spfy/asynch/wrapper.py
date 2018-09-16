#!/usr/bin/env python3
import fire
import kick

from .. import APP_NAME, config, logger
from ..constants import AuthFlow
from ..mixins.asynch import PlayerMixin, RecommenderMixin
from .client import SpotifyClient

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
        names = [name for name in names if not name.startswith("_") and name != "user"]
        return names

    async def auth(
        self, email=config.auth.email, username=config.auth.username, server=False
    ):
        if self.cli and not self.is_authenticated:
            if server:
                await self.authenticate(flow=AuthFlow.CLIENT_CREDENTIALS)
            else:
                try:
                    await self.authenticate(email=email, username=username)
                except Exception as exc:
                    logger.exception(exc)
        return self

    @staticmethod
    def update_config(name="config"):
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
        fire.Fire(spotify)
    except KeyboardInterrupt:
        print("Quitting")
    finally:
        if spotify.session and not Spotify.loop.is_running():
            Spotify.loop.run_until_complete(spotify.session.close())


if __name__ == "__main__":
    main()
