import random
import time
from datetime import date, timedelta
from itertools import chain

from pony.orm import get
from pony.orm.core import CacheIndexError

from .. import logger
from ..cache import Artist, Genre, Playlist, db_session, select
from ..constants import TimeRange
from ..util import normalize_features


class RecommenderMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @db_session
    def fetch_playlists(self):
        fetched_ids = set(select(p.id for p in Playlist))
        results = chain(
            self.user_playlists("particledetector").all(),
            self.user_playlists("thesoundsofspotify").all(),
        )
        for playlist in results:
            logger.info("Fetching %s", playlist.name)
            if playlist.id not in fetched_ids:
                Playlist.from_dict(playlist)
            fetched_ids.add(playlist.id)

    @db_session
    def fetch_user_top(self, time_range):
        self.user.top_artists.clear()
        for artist in self.current_user_top_artists(
            limit=50, time_range=time_range
        ).iterall():
            if self.is_disliked_artist(artist):
                continue

            if Artist.exists(id=artist.id):
                self.user.top_artists.add(Artist[artist.id])
            else:
                try:
                    artist = Artist.from_dict(artist)
                except CacheIndexError:
                    artist = Artist[artist.id]
                self.user.top_artists.add(artist)
        self.user.top_genres = (
            self.user.top_artists.genres.distinct().keys() - self.user.disliked_genres
        )
        if self.user.top_expires_at is None:
            self.user.top_expires_at = {}
        self.user.top_expires_at[TimeRange(time_range).value] = time.mktime(
            (date.today() + timedelta(days=1)).timetuple()
        )

    @db_session
    def genre_playlist(
        self, genre, popularity=Playlist.Popularity.SOUND
    ):  # pylint: disable=no-self-use
        if not Playlist.exists():
            raise Exception('You have to call "fetch_playlists" first.')

        return Playlist.get(
            genre=genre, popularity=Playlist.Popularity(popularity).value
        )

    @db_session
    def top_artists(self, time_range=TimeRange.SHORT_TERM):
        if self.user.top_expired(time_range):
            self.fetch_user_top(time_range)
        return self.user.top_artists

    @db_session
    def top_genres(self, time_range=TimeRange.SHORT_TERM):
        if self.user.top_expired(time_range):
            self.fetch_user_top(time_range)
        return self.user.top_genres

    def order_by(self, features, tracks):
        audio_features = self.audio_features(tracks=tracks)
        track_ids = [a.id for a in audio_features]
        audio_features = [a.to_dict(list(features.keys())) for a in audio_features]
        audio_features = normalize_features(audio_features, track_ids)
        for feature, direction in features.items():
            audio_features[feature] *= direction
        audio_features["total"] = audio_features.sum(axis=1)
        return audio_features.sort_values("total").index.tolist()

    def fill_with_related_artists(self, artists, limit=5):
        tries = 5
        if len(artists) >= limit:
            return artists

        artist_set = set(artists)
        artist_list = list(artists)
        while len(artist_set) < limit and tries:
            tries -= 1
            related_artists = {
                a.id
                for a in self.artist_related_artists(random.choice(artist_list))
                if self.is_not_disliked_artist(a)
            }
            related_artists_limit = min(
                random.randint(1, limit - len(artist_set)), len(related_artists)
            )
            artist_set |= set(random.sample(related_artists, related_artists_limit))
        return artist_set

    @db_session
    def recommend_by_top_artists(
        self,
        artist_limit=2,
        track_limit=100,
        use_related=True,
        features_order=None,
        time_range=TimeRange.SHORT_TERM,
        **kwargs,
    ):
        """Get a list of recommended songs.

        Returns:
            list: List of tracks
        """
        artists = (
            self.top_artists(time_range=time_range)
            .select()
            .without_distinct()
            .random(artist_limit)
        )
        if use_related:
            artists = self.fill_with_related_artists([a.id for a in artists])
        tracks = self.recommendations(seed_artists=artists, limit=track_limit, **kwargs)
        tracks = list(filter(self.is_not_disliked_track, tracks))
        if features_order:
            tracks = self.order_by(features_order, tracks)
        return tracks

    @db_session
    def is_disliked_artist(self, artist):
        return artist.id in set(
            self.user.disliked_artists.id.distinct().keys()
        ) or bool(set(artist.genres or []) & set(self.user.disliked_genres))

    @db_session
    def is_not_disliked_artist(self, artist):
        return not self.is_disliked_artist(artist)

    @db_session
    def is_not_disliked_track(self, track):
        return all(self.is_not_disliked_artist(a) for a in track.artists)

    @db_session
    def disliked_artists(self):
        return list(self.user.disliked_artists)

    @db_session
    def disliked_genres(self):
        return list(self.user.disliked_genres)

    @db_session
    def dislike_artist(self, artist):
        if isinstance(artist, str):
            # pylint: disable=consider-using-in
            artist = get(a for a in Artist if a.id == artist or a.name == artist)
        elif isinstance(artist, dict):
            artist = Artist.get(artist.id) or Artist.from_dict(artist)
        self.user.dislike(artist=artist)

    @db_session
    def dislike_genre(self, genre):
        if isinstance(genre, str):
            genre = genre.lower()
            genre = Genre.get(name=genre) or Genre(name=genre)
        self.user.dislike(genre=genre)
