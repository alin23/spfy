import re
import json
import random
from pathlib import Path
from collections import defaultdict

from pyorderby import orderby
from cached_property import cached_property

from .constants import TimeRange, AudioFeature, PlaylistType


class SpotifyRecommenderMixin:
    GENRE_RE = re.compile('The (?P<type>Sound|Pulse|Edge) of (?P<genre>.+)')
    PLAYLIST_CACHE = Path.home().joinpath('.particledetector')

    def __init__(self):
        pass

    @cached_property
    def particledetector_playlists(self):
        if self.PLAYLIST_CACHE.exists():
            return json.loads(self.PLAYLIST_CACHE.read_text())

        playlists = defaultdict(dict)
        results = self.all_results(self.user_playlists())
        for playlist in results:
            match = self.GENRE_RE.match(playlist.name)
            if match:
                type, genre = match.groups()
                playlists[genre.lower()][type.lower()] = playlist

        self.PLAYLIST_CACHE.write_text(json.dumps(playlists, indent=4))

        return playlists

    def cool_playlist(self, genre, type=PlaylistType.PULSE.value):
        return self.particledetector_playlists[genre][type]

    def all_top_artists(self, time_range=TimeRange.SHORT_TERM.value):
        return self.all_results(self.current_user_top_artists(limit=50, time_range=time_range))

    def top_genres(self, limit=10, time_range=TimeRange.SHORT_TERM.value):
        artists = self.all_top_artists(time_range)
        genres = {artist.genres for artist in artists}

        return random.sample(genres, limit) if limit else list(genres)

    def order_by(self, features, tracks):
        audio_features = self.audio_features(tracks=tracks)
        if isinstance(features, AudioFeature):
            features = features.value

        return sorted(audio_features, key=orderby(features))

    def recommend_by_top_artists(self, artist_limit=2, use_related=True, features_order=None, time_range=TimeRange.SHORT_TERM.value):
        """Get a list of recommended songs.

        Returns:
            list: List of tracks
        """

        artists = self.all_results(self.current_user_top_artists(limit=50, time_range=time_range))
        artists = random.sample(list(artists), artist_limit)
        while len(artists) < 5:
            related_artists_limit = random.randint(1, 5 - len(artists))
            artist = random.choice(artists)
            related_artists = self.artist_related_artists(artist)
            artists.append(random.sample(related_artists, related_artists_limit))

        tracks = super().recommendations(seed_artists=artists, limit=50)

        if features_order:
            tracks = self.order_by(features_order, tracks)

        return tracks
