import asyncio
import random
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import partial
from itertools import chain
from typing import Iterator

from pony.orm import db_session, get, select
from pony.orm.core import CacheIndexError
from unsplash.errors import UnsplashConnectionError, UnsplashError

from ... import logger
from ...asynch import LimitedAsCompletedError, limited_as_completed
from ...cache import Artist, City, Country, Genre, ImageMixin, Playlist, format_param
from ...constants import TimeRange
from ...sql import SQL
from ...util import normalize_features


class RecommenderMixin:
    USER_LIST = ("particledetector", "thesoundsofspotify")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def _get_upsert_genres_query(genres, conn):
        genre_names = ",\n".join(f"({format_param(genre)})" for genre in genres)
        return conn.execute(
            f"""INSERT INTO genres (name)
                VALUES {genre_names}
                ON CONFLICT DO NOTHING"""
        )

    @staticmethod
    def _get_upsert_countries_query(countries, conn):
        country_values = ",\n".join(
            f"({format_param(country.alpha_2)}, {format_param(country.name)})"
            for country in countries
            if country
        )
        return conn.execute(
            f"""INSERT INTO countries (code, name)
            VALUES {country_values}
            ON CONFLICT DO NOTHING"""
        )

    @staticmethod
    def _get_upsert_cities_query(cities, conn):
        city_values = ",\n".join(
            f"({format_param(city)}, {format_param(country)})"
            for city, country in cities
        )
        return conn.execute(
            f"""INSERT INTO cities (name, country)
                VALUES {city_values}
                ON CONFLICT DO NOTHING"""
        )

    @staticmethod
    def _get_upsert_playlists_queries(playlist_dicts, iso_countries):
        playlist_items = defaultdict(list)
        for p in playlist_dicts:
            if p.get("country"):
                if not iso_countries.get(p["country"]):
                    continue
                p["country"] = iso_countries[p["country"]].alpha_2
            playlist_items[tuple(p.keys())].append(p.values())

        queries = []
        for columns, value_list in playlist_items.items():
            column_string = ", ".join(columns)
            param_string = ",".join(
                f"({', '.join(format_param(p) for p in values)})"
                for values in value_list
            )
            queries.append(
                f"""INSERT INTO playlists AS p ({column_string})
                VALUES {param_string}
                ON CONFLICT DO NOTHING"""
            )

        return queries

    @staticmethod
    async def _get_unsplash_image_requests(conn, genres, countries, cities):
        image_requests = []
        if genres:
            image_genres = {
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT genre FROM images WHERE genre IS NOT NULL"
                )
            }
            new_genres = set(genres) - image_genres
            image_requests += [
                partial(Genre.get_image_fields, image_key=genre, genre=genre)
                for genre in new_genres
            ]

        if countries:
            image_countries = {
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT country FROM images WHERE country IS NOT NULL"
                )
            }
            country_dict = {c.alpha_2: c.name for c in countries.values() if c}
            new_countries = country_dict.keys() - image_countries
            image_requests += [
                partial(
                    Country.get_image_fields, image_key=country_dict[code], country=code
                )
                for code in new_countries
            ]
        if cities:
            image_cities = {
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT city FROM images WHERE city IS NOT NULL"
                )
            }
            city_country_mapping = dict(cities)
            new_cities = city_country_mapping.keys() - image_cities
            image_requests += [
                partial(
                    City.get_image_fields,
                    image_key=f"{city} {city_country_mapping[city]}",
                    city=city,
                )
                for city in new_cities
            ]

        return image_requests

    async def _upsert_remaining_images(self, reqs, initial_reqs):
        minutes = 62 - datetime.utcnow().minute
        delay = (minutes) * 60
        logger.info("Retrying image upsert in %d minutes", minutes)
        await asyncio.sleep(delay)
        await self._upsert_images(reqs, initial_reqs=initial_reqs)

    async def _upsert_images(self, reqs, conn=None, initial_reqs=None):
        conn = conn or await self.dbpool

        concurrency_limit = 100
        # pylint: disable=isinstance-second-argument-not-valid-type
        if not isinstance(reqs, Iterator):
            reqs_iterator = (fetch() for fetch in reqs)
        else:
            reqs_iterator = reqs

        try:
            async for resp in limited_as_completed(
                reqs_iterator,
                concurrency_limit,
                ignore_exceptions=(UnsplashError, UnsplashConnectionError),
            ):
                if not resp:
                    continue

                image_fields, updated_fields = resp
                await ImageMixin.upsert_unsplash_image(
                    conn, image_fields, **updated_fields
                )
        except LimitedAsCompletedError as exc:
            for future in exc.remaining_futures:
                future.cancel()

            await asyncio.sleep(2)
            for future in exc.remaining_futures:
                if future.done():
                    try:
                        _ = future.exception()
                    except:
                        pass

            remaining = len(list(reqs_iterator)) + concurrency_limit
            initial_reqs = initial_reqs or reqs

            if exc.original_exc:
                logger.exception(exc.original_exc)
            logger.warning(
                "Remaining images to fetch: %d/%d", remaining, len(initial_reqs)
            )

            asyncio.get_event_loop().create_task(
                self._upsert_remaining_images(
                    (fetch() for fetch in initial_reqs[-remaining:]), initial_reqs
                )
            )

    # pylint: disable=too-many-locals
    async def fetch_playlists_pg(self, conn=None):
        conn = conn or await self.dbpool

        existing_playlists = {
            p[0] for p in await conn.fetch("SELECT id FROM playlists")
        }
        user_ids_str = ",\n".join(f"('{user_id}')" for user_id in self.USER_LIST)
        await conn.execute(
            f"""
            INSERT INTO spotify_users (id)
            VALUES {user_ids_str}
            ON CONFLICT DO NOTHING
        """
        )

        playlist_dicts = []
        for user in self.USER_LIST:
            user_playlists = await self.user_playlists(user)
            async for playlist in user_playlists.iterall(ignore_exceptions=True):
                if not playlist:
                    continue

                logger.info("Got %s", playlist.name)
                if playlist.id not in existing_playlists:
                    playlist_dicts.append(Playlist.from_dict_pg(playlist))

                existing_playlists.add(playlist.id)

        genres = [p["genre"] for p in playlist_dicts if p.get("genre")]
        countries = [p["country"] for p in playlist_dicts if p.get("country")]
        iso_countries = {
            country: Country.get_iso_country(country) for country in countries
        }
        cities = [(p["city"], p["country"]) for p in playlist_dicts if p.get("city")]

        if genres:
            await self._get_upsert_genres_query(genres, conn)
        if countries:
            await self._get_upsert_countries_query(iso_countries.values(), conn)
        if cities:
            await self._get_upsert_cities_query(cities, conn)

        playlist_queries = self._get_upsert_playlists_queries(
            playlist_dicts, iso_countries
        )
        for query in playlist_queries:
            await conn.execute(query)

        image_requests = await self._get_unsplash_image_requests(
            conn, genres, iso_countries, cities
        )
        await self._upsert_images(image_requests, conn=conn)

    async def fetch_playlists(self):
        with db_session:
            fetched_ids = set(select(p.id for p in Playlist))
        for user in self.USER_LIST:
            user_playlists = await self.user_playlists(user)
            async for playlist in user_playlists.iterall(ignore_exceptions=True):
                if not playlist:
                    continue

                logger.info("Got %s", playlist.name)
                if playlist.id not in fetched_ids:
                    with db_session:
                        Playlist.from_dict(playlist)
                fetched_ids.add(playlist.id)

    async def fetch_user_top(self, time_range):
        with db_session:
            self.user.top_artists.clear()
            top_artists = await self.current_user_top_artists(
                limit=50, time_range=time_range
            )
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
            self.user.top_genres = (
                self.user.top_artists.genres.distinct().keys()
                - self.user.disliked_genres
            )
            if self.user.top_expires_at is None:
                self.user.top_expires_at = {}
            self.user.top_expires_at[TimeRange(time_range).value] = time.mktime(
                (date.today() + timedelta(days=1)).timetuple()
            )

    def genre_playlist(
        self, genre, popularity=Playlist.Popularity.SOUND
    ):  # pylint: disable=no-self-use
        with db_session:
            if not Playlist.exists():
                raise Exception('You have to call "fetch_playlists" first.')

            return Playlist.get(
                genre=genre, popularity=Playlist.Popularity(popularity).value
            )

    async def get_dislikes_for_filtering(self, conn=None):
        conn = conn or await self.dbpool

        dislikes = await conn.fetch(SQL.user_artist_genre_dislikes, self.user_id)

        disliked_artists = {row[0][:-3] for row in dislikes if row[0][-2:] == "AR"}
        disliked_genres = {row[0][:-3] for row in dislikes if row[0][-2:] == "GE"}
        return disliked_artists, disliked_genres

    async def top_artists_pg(
        self,
        time_range=TimeRange.SHORT_TERM,
        ignore=None,
        limit=None,
        conn=None,
        dislikes=None,
    ):
        conn = conn or await self.dbpool

        (
            disliked_artists,
            disliked_genres,
        ) = dislikes or await self.get_dislikes_for_filtering(conn)
        top_artists = await self.current_user_top_artists(
            limit=50, time_range=time_range
        )
        ignore = set(ignore or [])
        top_artists = [
            artist
            for artist in top_artists
            if not self.is_disliked_artist(artist, disliked_artists, disliked_genres)
            and artist.id not in ignore
        ]
        if limit:
            top_artists = random.sample(top_artists, min(limit, len(top_artists)))

        return top_artists

    async def top_genres_pg(
        self,
        time_range=TimeRange.SHORT_TERM,
        ignore=None,
        limit=None,
        conn=None,
        dislikes=None,
    ):
        conn = conn or await self.dbpool

        artists = await self.top_artists_pg(
            time_range=time_range, conn=conn, dislikes=dislikes
        )
        genres = set(chain.from_iterable(artist.genres for artist in artists))

        if ignore:
            genres -= set(ignore)
        if limit:
            genres = random.sample(genres, min(limit, len(genres)))

        return list(genres)

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
        if tracks and isinstance(tracks[0], str):
            tracks = list(set(tracks))

        audio_features, tracks = await asyncio.gather(
            self.audio_features(tracks=tracks), self.tracks(tracks=tracks)
        )

        audio_features_by_id = {a.id: a.to_dict() for a in audio_features if a}
        for track in tracks:
            track_features = audio_features_by_id.get(track.id)
            if track_features and track_features.get("popularity") is None:
                track_features["popularity"] = track.popularity or 0

        track_ids = list(audio_features_by_id.keys())
        audio_features = [
            {feature: a.get(feature) or 0 for feature in features.keys()}
            for a in audio_features_by_id.values()
        ]
        audio_features = normalize_features(audio_features, track_ids)
        for feature, direction in features.items():
            audio_features[feature] *= direction
        audio_features["total"] = audio_features.sum(axis=1)
        return audio_features.sort_values("total").index.tolist()

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
            related_artists_limit = min(
                random.randint(1, limit - len(artist_set)), len(related_artists)
            )
            artist_set |= set(random.sample(related_artists, related_artists_limit))
        return artist_set

    async def recommend_by_top_artists(
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
        with db_session:
            top_artists = await self.top_artists(time_range=time_range)
            artists = top_artists.select().without_distinct().random(artist_limit)
            if use_related:
                artists = await self.fill_with_related_artists([a.id for a in artists])
            tracks = await self.recommendations(
                seed_artists=artists, limit=track_limit, **kwargs
            )
            tracks = list(filter(self.is_not_disliked_track, tracks))
            if features_order:
                tracks = await self.order_by(features_order, tracks)
            return tracks

    def is_disliked_artist(self, artist, disliked_artists=None, disliked_genres=None):
        if disliked_artists is not None and disliked_genres is not None:
            return artist.id in disliked_artists or bool(
                set(artist.genres or []) & disliked_genres
            )
        with db_session:
            return artist.id in set(
                self.user.disliked_artists.id.distinct().keys()
            ) or bool(set(artist.genres or []) & set(self.user.disliked_genres))

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
                # pylint: disable=consider-using-in
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
