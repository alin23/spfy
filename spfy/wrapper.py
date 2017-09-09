#!/usr/bin/env python3
import os
import random
import inspect
import threading

import hug
import fire
from orderby import orderby
from cached_property import cached_property

from .log import get_logger
from .client import SpotifyClient
from .server import StandaloneApplication
from .volume import AlsaVolumeControl, SpotifyVolumeControl
from .constants import (
    VOLUME_FADE_SECONDS,
    Scope,
    AuthFlow,
    TimeRange,
    AudioFeature,
    VolumeBackend
)

logger = get_logger()


class Spotify(SpotifyClient):
    """Spotify high-level wrapper."""

    def __init__(
            self, email=None, port=None, flow=None, device=None,
            alsa_device=None, alsa_mixer=None, scope=None):
        email = email or os.getenv('SPOTIFY_EMAIL')
        port = int(port or os.getenv('SPOTIFY_PORT', 0))
        flow = flow or int(os.getenv('SPOTIFY_FLOW', AuthFlow.AUTHORIZATION_CODE))
        super().__init__(
            email=email, flow=flow, port=port,
            scope=scope or [scope.value for scope in Scope])

        self.device_name = device or os.getenv('SPOTIFY_DEVICE')
        self.alsa_device = alsa_device or os.getenv('SPOTIFY_ALSA_DEVICE')
        self.alsa_mixer = alsa_mixer or os.getenv('SPOTIFY_ALSA_MIXER')
        self.scope = scope or os.getenv('SPOTIFY_SCOPE') or [scope.value for scope in Scope]
        logger.debug(vars(self))

    def __dir__(self):
        names = super().__dir__()
        return [name for name in names if not name.startswith('_')]

    @cached_property
    def _device(self):
        return self.get_device(device=self.device_name)

    @cached_property
    def _alsa_volume_control(self):
        if os.uname().sysname != 'Linux':
            return

        return AlsaVolumeControl(self.alsa_mixer, device=self.alsa_device)

    @cached_property
    def _spotify_volume_control(self):
        return SpotifyVolumeControl(self, device=self._device)

    def change_volume(self, value=0, backend=VolumeBackend.SPOTIFY.value):
        assert backend in VolumeBackend or backend in [b.value for b in VolumeBackend]

        volume = None
        if backend == 'alsa':
            volume = self._alsa_volume_control.volume + value
            self._alsa_volume_control.volume = volume
        elif backend == 'spotify':
            volume = self._spotify_volume_control.volume + value
            self._spotify_volume_control.volume = volume

        return volume

    def volume_up(self, backend=VolumeBackend.SPOTIFY.value):
        return self.change_volume(value=+1, backend=backend)

    def volume_down(self, backend=VolumeBackend.SPOTIFY.value):
        return self.change_volume(value=-1, backend=backend)

    def recommendations(self, order_by=None, random_seed=False, *args, **kwargs):
        """Get a list of recommended songs.

        Returns:
            list: List of tracks
        """

        if random_seed:
            artists = self.all_results(self.current_user_top_artists(limit=50, time_range=TimeRange.SHORT_TERM.value))
            tracks = super().recommendations(seed_artists=random.sample(list(artists), 5), limit=50, *args, **kwargs)
        else:
            tracks = super().recommendations(*args, **kwargs)

        if order_by:
            audio_features = self.audio_features(tracks=tracks)
            if isinstance(order_by, AudioFeature):
                order_by = order_by.value
            tracks = sorted(audio_features, key=orderby(order_by))

        return tracks

    def play(self,
             recommendations=False, recommendations_order=None,
             fade=False, volume=80, fade_limit=100,
             fade_start=1, fade_step=1, fade_seconds=VOLUME_FADE_SECONDS, fade_force=False):
        tracks = None
        if recommendations:
            tracks = [t.uri for t in self.recommendations(random_seed=True, order_by=recommendations_order)]

        if fade:
            fadeargs = {
                'limit': fade_limit,
                'start': fade_start,
                'step': fade_step,
                'seconds': fade_seconds,
                'force': fade_force,
            }
            if self._alsa_volume_control:
                target = self._alsa_volume_control.fade
                self._spotify_volume_control.volume = volume
            else:
                target = self._spotify_volume_control.fade
                self._alsa_volume_control.volume = volume

            threading.Thread(target=target, kwargs=fadeargs).start()

        return self.start_playback(tracks=tracks, device_id=self._device.id)

    def server(self, **options):
        for name, method in inspect.getmembers(self, inspect.ismethod):
            hug.get(f'/{name}')(method)

        from .client import __hug__ as client_hug
        __hug__.extend(client_hug)  # noqa

        app = StandaloneApplication(__hug_wsgi__, **options)  # noqa
        app.run()


def main():
    """Main function."""

    try:
        fire.Fire(Spotify)
    except KeyboardInterrupt:
        print('Quitting')


if __name__ == '__main__':
    main()
