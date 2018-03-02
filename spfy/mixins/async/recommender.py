import time
import random
from datetime import date, timedelta

from pony.orm.core import CacheIndexError

from ... import logger
from ...util import normalize_features
from ...cache import Genre, Artist, Playlist, get, select, db_session
from ...constants import TimeRange


class RecommenderMixin:
    USER_LIST = ('particledetector', 'thesoundsofspotify')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def fetch_playlists(self):
        with db_session:
            fetched_ids = set(select(p.id for p in Playlist))

            for user in self.USER_LIST:
                user_playlists = await self.user_playlists(user)
                async for playlist in user_playlists.iterall():
                    logger.info(f'Got {playlist.name}')
                    if playlist.id not in fetched_ids:
                        Playlist.from_dict(playlist)
                    fetched_ids.add(playlist.id)

    async def fetch_user_top(self, time_range):
        with db_session:
            self.user.top_artists.clear()
            top_artists = await self.current_user_top_artists(limit=50, time_range=time_range)
            async for artist in top_artists.iterall():
                if self.is_disliked_artist(artist):
                    continue

                if Artist.exists(id=artist.id):
                    self.user.top_artists.add(Artist[artist.id])
                else:
                    try:
                        artist = await Artist.from_dict_async(artist)
                    except CacheIndexError:
                        artist = Artist[artist.id]
                    self.user.top_artists.add(artist)

            self.user.top_genres = self.user.top_artists.genres.distinct().keys() - self.user.disliked_genres

            if self.user.top_expires_at is None:
                self.user.top_expires_at = {}
            self.user.top_expires_at[TimeRange(time_range).value] = time.mktime(
                (date.today() + timedelta(days=1)).timetuple()
            )

    def genre_playlist(self, genre, popularity=Playlist.Popularity.SOUND):  # pylint: disable=no-self-use
        with db_session:
            if not Playlist.exists():
                raise Exception('You have to call "fetch_playlists" first.')
            return Playlist.get(genre=genre, popularity=Playlist.Popularity(popularity).value)

    async def top_artists(self, time_range=TimeRange.SHORT_TERM):
        with db_session:
            if self.user.top_expired(time_range):
                await self.fetch_user_top(time_range)

            return self.user.top_artists

    async def top_genres(self, time_range=TimeRange.SHORT_TERM):
        with db_session:
            if self.user.top_expired(time_range):
                await self.fetch_user_top(time_range)

            return self.user.top_genres

    async def order_by(self, features, tracks):
        audio_features = await self.audio_features(tracks=tracks)
        audio_features = [a.to_dict(list(features.keys()) + ['id']) for a in audio_features]
        audio_features = normalize_features(features, audio_features)

        return audio_features.sort_values().index.tolist()

    async def fill_with_related_artists(self, artists, limit=5):
        tries = 5
        if len(artists) >= limit:
            return artists

        artist_set = set(artists)
        artist_list = list(artists)

        while len(artist_set) < limit and tries:
            tries -= 1
            related_artists = {
                a.id
                for a in (await self.artist_related_artists(random.choice(artist_list)))
                if self.is_not_disliked_artist(a)
            }

            related_artists_limit = min(random.randint(1, limit - len(artist_set)), len(related_artists))
            artist_set |= set(random.sample(related_artists, related_artists_limit))

        return artist_set

    async def recommend_by_top_artists(
        self,
        artist_limit=2,
        track_limit=100,
        use_related=True,
        features_order=None,
        time_range=TimeRange.SHORT_TERM,
        **kwargs
    ):
        """Get a list of recommended songs.

        Returns:
            list: List of tracks
        """

        with db_session:
            top_artists = await self.top_artists(time_range=time_range)
            artists = top_artists.select().without_distinct().random(artist_limit)
            if use_related:
                artists = await self.fill_with_related_artists([a.id for a in artists])

            tracks = await self.recommendations(seed_artists=artists, limit=track_limit, **kwargs)
            tracks = list(filter(self.is_not_disliked_track, tracks))

            if features_order:
                tracks = await self.order_by(features_order, tracks)

            return tracks

    def is_disliked_artist(self, artist):
        with db_session:
            return (
                artist.id in set(self.user.disliked_artists.id.distinct().keys())
                or bool(set(artist.genres or []) & set(self.user.disliked_genres))
            )

    def is_not_disliked_artist(self, artist):
        with db_session:
            return not self.is_disliked_artist(artist)

    def is_not_disliked_track(self, track):
        with db_session:
            return all(self.is_not_disliked_artist(a) for a in track.artists)

    def disliked_artists(self):
        with db_session:
            return list(self.user.disliked_artists)

    def disliked_genres(self):
        with db_session:
            return list(self.user.disliked_genres)

    async def dislike_artist(self, artist):
        with db_session:
            if isinstance(artist, str):
                artist = get(a for a in Artist if a.id == artist or a.name == artist)
            elif isinstance(artist, dict):
                artist = Artist.get(artist.id) or (await Artist.from_dict_async(artist))

            self.user.dislike(artist=artist)

    def dislike_genre(self, genre):
        with db_session:
            if isinstance(genre, str):
                genre = genre.lower()
                genre = Genre.get(name=genre) or Genre(name=genre)

            self.user.dislike(genre=genre)
