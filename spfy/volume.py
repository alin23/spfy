import os
import abc
from time import sleep

from .log import get_logger
from .util import SpotifyResult
from .constants import VOLUME_FADE_SECONDS

logger = get_logger()

if os.uname().sysname == 'Linux':
    import alsaaudio


class VolumeControl(abc.ABC):
    @abc.abstractmethod
    def unmute(self):
        pass

    @abc.abstractmethod
    def mute(self):
        pass

    @abc.abstractproperty
    def volume(self):
        pass

    @volume.setter
    def volume(self, val):
        pass

    def fade(self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False):
        self.unmute()

        delay = seconds / ((limit - start) / step)
        device_volume = self.volume

        self.volume = start

        for next_volume in range(start + step, limit + 1, step):
            sleep(delay)
            device_volume = self.volume
            old_volume = next_volume - step

            if abs(device_volume - old_volume) > 1 and not force:
                logger.debug(f'''Volume has been changed manually:
                    Current volume: {device_volume}
                    Old volume: {old_volume}''')
                break

            logger.debug(f'Setting volume to {next_volume}')
            self.volume = next_volume


class SpotifyVolumeControl(VolumeControl):
    def __init__(self, client, device=None):
        self.spotify = client
        self.device = device
        self.volume_before_mute = None
        if not isinstance(device, SpotifyResult):
            self.device = self.get_device(device=device)

    def mute(self):
        self.volume_before_mute = self.volume
        self.spotify.volume(0, device_id=self.device.id)

    def unmute(self):
        if self.volume_before_mute:
            self.volume = self.volume_before_mute

    @property
    def volume(self):
        return int(self.spotify.get_device(device=self.device.id).volume_percent) + 1

    @volume.setter
    def volume(self, val):
        self.spotify.volume(max(val, 1), device_id=self.device.id)


class AlsaVolumeControl(VolumeControl):
    def __init__(self, mixer_name, device=None):
        if isinstance(device, str):
            kwargs = dict(device=device)
        elif isinstance(device, int):
            kwargs = dict(cardindex=device)
        else:
            kwargs = dict()

        self.mixer = alsaaudio.Mixer(mixer_name, **kwargs)

    def mute(self):
        self.mixer.setmute(1)

    def unmute(self):
        self.mixer.setmute(0)

    @property
    def volume(self):
        vol = self.mixer.getvolume()
        return sum(vol) // len(vol)

    @volume.setter
    def volume(self, val):
        self.mixer.setvolume(max(val, 1))
