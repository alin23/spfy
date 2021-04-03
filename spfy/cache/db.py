# pylint: disable=too-many-lines
import asyncio
import os
import random
import re
import string
import time
from collections import OrderedDict
from datetime import date, datetime
from enum import IntEnum
from io import BytesIO
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import aiohttp
import psycopg2.extras
import requests
from colorthief import ColorThief
from first import first
from pony.orm import (
    Database,
    Json,
    ObjectNotFound,
    Optional,
    PrimaryKey,
    Required,
    Set,
    db_session,
    desc,
    ormtypes,
    select,
    sql_debug,
)
from pony.orm.core import CacheIndexError
from psycopg2.extensions import register_adapter
from pycountry import countries
from unsplash.errors import UnsplashConnectionError, UnsplashError

from .. import Unsplash, config, logger
from ..constants import TimeRange
from ..sql import SQL, SQL_DEFAULT

DIGITS_PATTERN = re.compile(r"[0-9]")
register_adapter(ormtypes.TrackedDict, psycopg2.extras.Json)
if os.getenv("SQL_DEBUG"):
    sql_debug(True)
    import logging

    logging.getLogger("pony.orm.sql").setLevel(logging.DEBUG)
db = Database()


def create_condition(op="AND", firstsub=1, **fields):
    condition = f" {op} ".join(
        f"{field} = ${i + firstsub}" for i, field in enumerate(fields.keys())
    )
    return condition


def format_param(param):
    if isinstance(param, (int, float, bool)):
        return str(param)
    if isinstance(param, (str, bytes, dict, date, datetime, UUID)):
        tag = "".join(random.sample(string.ascii_letters, 3))
        return f"${tag}${param}${tag}$"
    if param is None:
        return "null"
    return param


class ImageMixin:
    @classmethod
    async def image_pg(cls, conn, width=None, height=None, **fields):
        condition = create_condition(firstsub=2, **fields)
        if width:
            image = await conn.fetchrow(
                f"SELECT * FROM images WHERE width >= $1 AND {condition} ORDER BY width LIMIT 1",
                width,
                *fields.values(),
            )
        elif height:
            image = await conn.fetchrow(
                f"SELECT * FROM images WHERE height >= $1 AND {condition} ORDER BY height LIMIT 1",
                height,
                *fields.values(),
            )
        else:
            image = await conn.fetchrow(
                f"SELECT * FROM images WHERE {condition} ORDER BY width DESC LIMIT 1",
                *fields.values(),
            )
        return image

    def image(self, width=None, height=None):
        if width:
            image = (
                self.images.select()
                .where(lambda i: i.width >= width)
                .order_by(Image.width)
                .first()
            )
        elif height:
            image = (
                self.images.select()
                .where(lambda i: i.height >= height)
                .order_by(Image.height)
                .first()
            )
        else:
            image = self.images.select().order_by(desc(Image.width)).first()
        return image

    @classmethod
    def get_image_queries_pg(cls, key):
        words = key.split()
        stems = [[w[:i] for i in range(len(w), 2, -1)] for w in words]
        queries = [key, *words, *sum(stems, [])]
        return queries + [f"{query} music" for query in queries]

    def get_image_queries(self):
        words = self.name.split()
        stems = [[w[:i] for i in range(len(w), 2, -1)] for w in words]
        queries = [*words, self.name, *sum(stems, [])]
        return [f"{query} music" for query in queries]

    @classmethod
    async def get_image_fields(cls, image_key=None, **fields):
        logger.info("Getting image for key=%s %s", image_key, fields)

        key = image_key or " ".join(str(v) for v in fields.values())
        queries = cls.get_image_queries_pg(key)

        photo = await cls.get_unsplash_photo(queries)
        if photo is None:
            return None

        ratio = photo.height / photo.width
        params = {
            "color": photo.color,
            "unsplash_id": photo.id,
            "unsplash_user_fullname": photo.user.name,
            "unsplash_user_username": photo.user.username,
            **fields,
        }
        image_fields = [
            {
                **params,
                "url": photo.urls.full,
                "width": photo.width,
                "height": photo.height,
            },
            {
                **params,
                "url": photo.urls.regular,
                "width": Image.REGULAR,
                "height": int(round(ratio * Image.REGULAR)),
            },
            {
                **params,
                "url": photo.urls.small,
                "width": Image.SMALL,
                "height": int(round(ratio * Image.SMALL)),
            },
            {
                **params,
                "url": photo.urls.thumb,
                "width": Image.THUMB,
                "height": int(round(ratio * Image.THUMB)),
            },
        ]
        image_fields = [
            OrderedDict(sorted(d.items(), key=lambda t: t[0])) for d in image_fields
        ]

        return image_fields, fields

    @classmethod
    async def upsert_unsplash_image(cls, conn, image_fields, **updated_fields):
        logger.debug(
            "Upserting image: %s | UPDATED: [%s]", image_fields, updated_fields
        )

        columns = ", ".join(image_fields[0].keys())
        values = ",\n".join(
            f"({', '.join([format_param(p) for p in im.values()])})"
            for im in image_fields
        )
        updated_fields_str = ", ".join(
            f"{col} = ${i+1}" for i, col in enumerate(updated_fields.keys())
        )
        images = await conn.fetch(
            f"""INSERT INTO images AS im ({columns})
            VALUES {values}
            ON CONFLICT (url) DO UPDATE SET {updated_fields_str}
            RETURNING *
            """,
            *updated_fields.values(),
        )
        return [dict(i) for i in images]

    @classmethod
    async def fetch_unsplash_image_pg(
        cls, conn, width=None, height=None, image_key=None, **fields
    ):
        image_fields, updated_fields = await cls.get_image_fields(image_key, **fields)
        images = await cls.upsert_unsplash_image(conn, image_fields, **updated_fields)

        if not images:
            return None
        return cls.get_optimal_image(images, width=width, height=height)

    @staticmethod
    def get_optimal_image(images, width=None, height=None):
        images = sorted(images, key=lambda i: i.get("width" or 0))
        if width:
            return first(
                images, key=lambda i: (i.get("width") or 0) >= width, default=images[0]
            )
        if height:
            return first(
                images,
                key=lambda i: (i.get("height") or 0) >= height,
                default=images[0],
            )
        return images[0]

    @staticmethod
    async def get_unsplash_photo(queries):
        photo = None
        for query in queries:
            try:
                photos = await Unsplash.photo.random(
                    query=query, orientation="squarish"
                )
            except (UnsplashError, UnsplashConnectionError):
                continue

            if photos:
                photo = photos[0]
                break

        else:
            try:
                photo = (
                    await Unsplash.photo.random(query="music", orientation="squarish")
                )[0]
            except (UnsplashError, UnsplashConnectionError):
                photo = None
        return photo

    async def fetch_unsplash_image(self, width=None, height=None):
        image = self.image(width, height)
        if image:
            return image

        queries = self.get_image_queries()
        photo = await self.get_unsplash_photo(queries)
        if photo is None:
            return None

        images = select(i for i in Image if i.unsplash_id == photo.id).for_update()
        if images.exists():
            params = {self.__class__.__name__.lower(): self}
            for image in images:
                image.set(**params)
            return self.image(width, height)

        params = {self.__class__.__name__.lower(): self, "unsplash_id": photo.id}
        image_exists = False
        for url in (
            photo.urls.full,
            photo.urls.regular,
            photo.urls.small,
            photo.urls.thumb,
        ):
            image = Image.get(url=url)
            if image:
                image_exists = True
                image.set(**params)
        if image_exists:
            return self.image(width, height)

        ratio = photo.height / photo.width
        params = {
            self.__class__.__name__.lower(): self,
            "color": photo.color,
            "unsplash_id": photo.id,
            "unsplash_user_fullname": photo.user.name,
            "unsplash_user_username": photo.user.username,
        }
        Image(url=photo.urls.full, width=photo.width, height=photo.height, **params)
        Image(
            url=photo.urls.regular,
            width=Image.REGULAR,
            height=int(round(ratio * Image.REGULAR)),
            **params,
        )
        Image(
            url=photo.urls.small,
            width=Image.SMALL,
            height=int(round(ratio * Image.SMALL)),
            **params,
        )
        Image(
            url=photo.urls.thumb,
            width=Image.THUMB,
            height=int(round(ratio * Image.THUMB)),
            **params,
        )
        return self.image(width, height)


class User(db.Entity, ImageMixin):
    _table_ = "users"
    DEFAULT_EMAIL = "spfy@backend"
    DEFAULT_USERNAME = "spfy-backend"
    DEFAULT_USERID = uuid5(NAMESPACE_URL, DEFAULT_USERNAME)
    id = PrimaryKey(
        UUID, default=uuid4, sql_default=SQL_DEFAULT.uuid4
    )  # pylint: disable=redefined-builtin
    email = Optional(str, unique=True, index=True, sql_default="''")
    username = Required(str, unique=True, index=True)
    country = Required("Country")
    preferred_country = Optional("Country")
    spotify_user = Optional("SpotifyUser")
    display_name = Optional(str, sql_default="''")
    birthdate = Optional(date)
    token = Required(Json, volatile=True)
    spotify_premium = Required(bool)
    api_calls = Required(int, default=0, sql_default="0", volatile=True)
    created_at = Required(
        datetime, default=datetime.utcnow, sql_default=SQL_DEFAULT.now
    )
    last_usage_at = Required(
        datetime, default=datetime.utcnow, sql_default=SQL_DEFAULT.now, volatile=True
    )
    images = Set("Image", cascade_delete=True)
    top_artists = Set("Artist")
    disliked_artists = Set("Artist")
    top_genres = Set("Genre")
    disliked_genres = Set("Genre")
    top_countries = Set("Country")
    disliked_countries = Set("Country")
    top_cities = Set("City")
    disliked_cities = Set("City")
    top_expires_at = Required(Json, volatile=True, default=dict, sql_default="'{}'")

    # pylint: disable=arguments-differ,signature-differs
    def to_dict(self, *args, **kwargs):
        _dict = super().to_dict(*args, **kwargs)
        if "id" in _dict:
            _dict["id"] = str(_dict["id"])
        return _dict

    @classmethod
    async def from_dict_async(cls, user):
        if user.images:
            try:
                color = await Image.grab_color_async(user.images[-1].url)
            except:
                color = "#000000"
            for image in user.images:
                image.color = color
        return cls.from_dict(user, grab_image_color=False)

    @classmethod
    def from_dict(cls, user, grab_image_color=True):
        if user.images and grab_image_color:
            try:
                color = Image.grab_color(user.images[-1].url)
            except:
                color = "#000000"
            for image in user.images:
                image.color = color
        images = [Image.get(url=image.url) or Image(**image) for image in user.images]
        spotify_user = SpotifyUser.get(id=user.id) or SpotifyUser(
            id=user.id, name=user.get("display_name") or ""
        )
        return cls(
            id=user.user_id,
            spotify_premium=user.product == "premium",
            spotify_user=spotify_user,
            username=user.id,
            email=user.email or str(user.user_id),
            token=user.token,
            country=Country.from_str(user.country),
            images=images,
            display_name=user.display_name or "",
            birthdate=datetime.strptime(user.birthdate, "%Y-%m-%d")
            if user.birthdate
            else None,
        )

    async def _fetch_artist(self, artist, client):
        if artist and client:
            if Artist.exists(id=artist):
                return artist

            artist_result = await client.artist(artist)
            if not artist_result:
                return artist

            try:
                with db_session:
                    # pylint: disable=unused-variable
                    artist_row = await Artist.from_dict_async(artist_result)
            except CacheIndexError:
                pass
        return artist

    async def dislike_async(
        self, artist=None, genre=None, country=None, city=None, client=None
    ):
        artist = await self._fetch_artist(artist, client)
        self.dislike(artist=artist, genre=genre, country=country, city=city)

    async def like_async(
        self, artist=None, genre=None, country=None, city=None, client=None
    ):
        artist = await self._fetch_artist(artist, client)
        self.like(artist=artist, genre=genre, country=country, city=city)

    def dislike(self, artist=None, genre=None, country=None, city=None):
        assert artist or genre or country or city
        if artist:
            artist = Artist.get(id=artist)
            if artist:
                self.disliked_artists.add(artist)
                self.top_artists.remove(artist)
        if genre:
            genre = Genre.get(name=genre) or Genre(name=genre)
            if genre:
                self.disliked_genres.add(genre)
                self.top_genres.remove(genre)
                self.disliked_artists.add(genre.artists)
                self.top_artists.remove(genre.artists)
        if country:
            country = Country.get(code=country)
            if country:
                self.disliked_countries.add(country)
                self.top_countries.remove(country)
        if city:
            city = City.get(name=city)
            if city:
                self.disliked_cities.add(city)
                self.top_cities.remove(city)

    def like(self, artist=None, genre=None, country=None, city=None):
        assert artist or genre or country or city
        if artist:
            artist = Artist.get(id=artist)
            if artist:
                self.top_artists.add(artist)
                self.disliked_artists.remove(artist)
        if genre:
            genre = Genre.get(name=genre)
            if genre:
                self.top_genres.add(genre)
                self.disliked_genres.remove(genre)
                self.top_artists.add(genre.artists)
                self.disliked_artists.remove(genre.artists)
        if country:
            country = Country.get(code=country)
            if country:
                self.top_countries.add(country)
                self.disliked_countries.remove(country)
        if city:
            city = City.get(name=city)
            if city:
                self.top_cities.add(city)
                self.disliked_cities.remove(city)

    @classmethod
    async def like_pg(cls, conn, user_id, **kwargs):
        for key, value in kwargs.items():
            await conn.execute(SQL.like.format(key), user_id, value)

    @classmethod
    async def dislike_pg(cls, conn, spotify, **kwargs):
        artist = kwargs.pop("artist", None)
        if artist:
            artist = await spotify.artist(artist)
            await conn.execute(
                SQL.dislike_artist.format("artist"),
                spotify.user_id,
                artist.id,
                artist.name,
                artist.followers.total or 0,
                artist.popularity or 0,
            )
        for key, value in kwargs.items():
            await conn.execute(SQL.dislike.format(key), spotify.user_id, value)

    def top_expired(self, time_range):
        time_range = TimeRange(time_range).value
        return (
            not self.top_expires_at
            or time_range not in self.top_expires_at
            or time.time() >= self.top_expires_at[time_range]
        )

    @classmethod
    def default(cls):
        try:
            return User[cls.DEFAULT_USERID]

        except ObjectNotFound:
            return User(
                id=cls.DEFAULT_USERID,
                username=cls.DEFAULT_USERNAME,
                email=cls.DEFAULT_EMAIL,
                token={},
                country=Country.from_str("US"),
                spotify_premium=False,
            )

    @staticmethod
    def token_updater(_id):
        @db_session
        def update(token):
            User[_id].token = token

        return update


class Image(db.Entity):
    _table_ = "images"
    REGULAR = 1080
    SMALL = 400
    THUMB = 200
    url = PrimaryKey(str)
    height = Optional(int)
    width = Optional(int)
    color = Optional(str, sql_default="''")
    playlist = Optional("Playlist")
    artist = Optional("Artist")
    genre = Optional("Genre")
    country = Optional("Country")
    city = Optional("City")
    user = Optional("User")
    unsplash_id = Optional(str, index=True, sql_default="''")
    unsplash_user_fullname = Optional(str, sql_default="''")
    unsplash_user_username = Optional(str, sql_default="''")

    # pylint: disable=no-self-use

    @classmethod
    def unsplash_url(cls):
        return f"https://unsplash.com/?utm_source={config.unsplash.app_name}&utm_medium=referral"

    @classmethod
    def unsplash_user_url(cls, username):
        return f"https://unsplash.com/@{username}?utm_source={config.unsplash.app_name}&utm_medium=referral"

    @classmethod
    def unsplash_credits(cls, user_fullname, username):
        return {
            "user_name": user_fullname,
            "user_url": cls.unsplash_user_url(username),
            "site_url": cls.unsplash_url(),
        }

    @staticmethod
    async def grab_color_async(image_url):
        async with aiohttp.ClientSession() as client:
            async with client.get(image_url) as resp:
                image_file = BytesIO(await resp.read())
                color = ColorThief(image_file).get_color(quality=1)
                return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    @staticmethod
    def grab_color(image_url):
        resp = requests.get(image_url)
        image_file = BytesIO(resp.content)
        color = ColorThief(image_file).get_color(quality=1)
        return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    @classmethod
    async def download_pg(cls, conn, url):
        unsplash_id = await conn.fetchval(
            "SELECT unsplash_id FROM images WHERE url = $1", url
        )
        image = None
        async with aiohttp.ClientSession() as client:
            async with client.get(url) as resp:
                _, image = await asyncio.gather(
                    Unsplash.photo.download(unsplash_id, without_content=True),
                    resp.read(),
                )
        return image

    async def download(self):
        image = None
        async with aiohttp.ClientSession() as client:
            async with client.get(self.url) as resp:
                _, image = await asyncio.gather(
                    Unsplash.photo.download(self.unsplash_id, without_content=True),
                    resp.read(),
                )
        return image


class SpotifyUser(db.Entity):
    _table_ = "spotify_users"
    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
    name = Optional(str, sql_default="''")
    user = Optional("User")
    playlists = Set("Playlist")

    @property
    def uri(self):
        return f"spotify:user:{self.id}"

    @property
    def href(self):
        return f"https://api.spotify.com/v1/users/{self.id}"

    @property
    def external_url(self):
        return f"http://open.spotify.com/user/{self.id}"


class Genre(db.Entity, ImageMixin):
    _table_ = "genres"
    name = PrimaryKey(str)
    artists = Set("Artist")
    playlists = Set("Playlist")
    fans = Set(User, reverse="top_genres", table="genre_fans")
    haters = Set(User, reverse="disliked_genres", table="genre_haters")
    images = Set(Image, cascade_delete=True)

    def play(self, client, device=None):
        popularity = random.choice(list(Playlist.Popularity)[:3])
        playlist = client.genre_playlist(self.name, popularity)
        return playlist.play(device=device)


class Country(db.Entity, ImageMixin):
    _table_ = "countries"
    code = PrimaryKey(str, max_len=2)
    name = Required(str, index=True)
    users = Set("User", reverse="country")
    users_preferring = Set("User", reverse="preferred_country")
    cities = Set("City")
    playlists = Set("Playlist")
    fans = Set(User, reverse="top_countries", table="country_fans")
    haters = Set(User, reverse="disliked_countries", table="country_haters")
    images = Set(Image, cascade_delete=True)

    @staticmethod
    def _name_match(country, name):
        try:
            return name in country.name.lower() or name in country.official_name.lower()

        except:
            return False

    @classmethod
    def get_iso_country(cls, country):
        iso_country, code, name = None, None, None
        if len(country) == 2:
            code = country
        else:
            name = country

        if country == "UK":
            iso_country = countries.get(alpha_2="GB")
        elif country == "USA":
            iso_country = countries.get(alpha_2="US")
        elif code is not None:
            try:
                iso_country = countries.get(alpha_2=code)
            except KeyError:
                iso_country = first(
                    countries, key=lambda c: code.lower() in c.alpha_2.lower()
                )
        elif name is not None:
            try:
                iso_country = countries.get(name=name)
            except KeyError:
                try:
                    iso_country = countries.get(official_name=name)
                except KeyError:
                    try:
                        iso_country = countries.get(common_name=name)
                    except KeyError:
                        iso_country = first(
                            countries, key=lambda c: cls._name_match(c, name.lower())
                        )
        if not iso_country:
            logger.error(
                "Could not find a country with name=%s and code=%s", name, code
            )
            return None
        return iso_country

    @classmethod
    def from_str(cls, country):
        iso_country = cls.get_iso_country(country)
        if not iso_country:
            return None

        return cls.get(name=iso_country.name) or cls(
            name=iso_country.name, code=iso_country.alpha_2
        )

    def get_image_queries(self):
        words = self.name.split()
        stems = [[w[:i] for i in range(len(w), 2, -1)] for w in words]
        queries = [self.name, *words, *sum(stems, [])]
        return queries


class City(db.Entity, ImageMixin):
    _table_ = "cities"
    name = PrimaryKey(str)
    country = Required(Country)
    playlists = Set("Playlist")
    fans = Set(User, reverse="top_cities", table="city_fans")
    haters = Set(User, reverse="disliked_cities", table="city_haters")
    images = Set(Image, cascade_delete=True)

    def get_image_queries(self):
        words = self.name.split()
        stems = [[w[:i] for i in range(len(w), 2, -1)] for w in words]
        queries = [self.name, self.country.name, *words, *sum(stems, [])]
        return queries


class Playlist(db.Entity, ImageMixin):
    _table_ = "playlists"
    YEAR = "(?P<year>[0-9]{4})"
    GENRE = "(?P<genre>.+)"
    CITY = "(?P<city>.+)"
    COUNTRY = "(?P<country>.+?)"
    COUNTRY_CODE = "(?P<country_code>[A-Z]{2})"
    DATE = "(?P<date>[0-9]{8})"
    INTRO_POPULARITY = "(?P<popularity>Intro)"
    GENRE_POPULARITY_TITLE = "(?P<popularity>Sound|Pulse|Edge)"
    GENRE_POPULARITY_LOWER = "(?P<popularity>sound|pulse|edge)"
    NEEDLE_POPULARITY = "(?P<popularity>Current|Emerging|Underground)"
    PATTERNS = OrderedDict(
        intro_to_genre=re.compile(f"^{INTRO_POPULARITY} to {GENRE}$"),
        sound_of_city=re.compile(f"^The Sound of {CITY} {COUNTRY_CODE}$"),
        needle=re.compile(f"^The Needle / {COUNTRY}(?: - {NEEDLE_POPULARITY})?$"),
        pine_needle=re.compile(f"^The Pine Needle / {COUNTRY}$"),
        year_in_genre=re.compile(f"^{YEAR} in {GENRE}$"),
        meta_genre=re.compile(f"^Meta{GENRE_POPULARITY_LOWER}: {GENRE}$"),
        meta_year_in_genre=re.compile(f"^Meta{YEAR}: {GENRE}$"),
        sound_of_genre=re.compile(f"^The {GENRE_POPULARITY_TITLE} of {GENRE}$"),
        women_filter_genre=re.compile(f"^A ♀Filter for {GENRE}$"),
    )

    class Popularity(IntEnum):
        SOUND = 0
        PULSE = 1
        EDGE = 2
        CURRENT = 3
        EMERGING = 4
        UNDERGROUND = 5
        YEAR = 6
        ALL = 7
        INTRO = 8

    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
    collaborative = Required(bool)
    name = Required(str)
    description = Optional(str, sql_default="''")
    owner = Required(SpotifyUser)
    public = Required(bool)
    snapshot_id = Required(str)
    tracks = Required(int)
    popularity = Optional(int, index=True, sql_default="0")
    genre = Optional(Genre)
    country = Optional(Country)
    city = Optional(City)
    date = Optional(date, index=True)
    year = Optional(int)
    women = Optional(bool, index=True, sql_default=SQL_DEFAULT.bool_false)
    christmas = Optional(bool, index=True, sql_default=SQL_DEFAULT.bool_false)
    meta = Optional(bool, index=True, sql_default=SQL_DEFAULT.bool_false)
    images = Set(Image, cascade_delete=True)

    def play(self, client, device=None):
        return client.start_playback(playlist=self.uri, device=device)

    @property
    def uri(self):
        return f"spotify:user:{self.owner.id}:playlist:{self.id}"

    @property
    def href(self):
        return f"https://api.spotify.com/v1/users/{self.owner.id}/playlists/{self.id}"

    @property
    def external_url(self):
        return f"http://open.spotify.com/user/{self.owner.id}/playlist/{self.id}"

    @classmethod
    def get_fields(cls, groups):
        fields = {}
        if "year" in groups:
            fields["year"] = int(groups["year"])
            fields["date"] = date(fields["year"], 1, 1)
            fields["popularity"] = cls.Popularity.YEAR.value
        if "city" in groups and "country_code" in groups:
            fields["country"] = groups["country_code"]
            fields["city"] = groups["city"]
            fields["popularity"] = cls.Popularity.SOUND.value
        if "genre" in groups:
            genre = groups["genre"].lower()
            fields["genre"] = genre
            if "christmas" in genre:
                fields["christmas"] = True
        if "country" in groups:
            fields["country"] = groups["country"]
        if groups.get("date"):
            fields["date"] = datetime.strptime(groups["date"], "%Y%m%d").date()
        if "popularity" in groups:
            popularity = groups["popularity"]
            if popularity:
                fields["popularity"] = cls.Popularity[popularity.upper()].value
            else:
                fields["popularity"] = cls.Popularity.ALL.value
        return fields

    @classmethod
    def from_dict_pg(cls, playlist):
        fields = {
            "id": playlist.id,
            "description": playlist.description or "",
            "collaborative": playlist.collaborative,
            "name": playlist.name,
            "owner": playlist.owner.id,
            "public": playlist.public,
            "snapshot_id": playlist.snapshot_id,
            "tracks": playlist.tracks.total,
            "women": playlist.name.startswith("A ♀Filter for"),
            "christmas": (
                "Pine Needle" in playlist.name or "christmas" in playlist.name.lower()
            ),
            "meta": playlist.name.startswith("Meta"),
        }
        for pattern in cls.PATTERNS.values():
            match = pattern.match(playlist.name)
            if match:
                groups = match.groupdict()
                fields.update(cls.get_fields(groups))
                break

        else:
            logger.warning("No pattern matches the playlist: %s", playlist.name)
        return fields

    @classmethod
    def from_dict(cls, playlist):
        owner = SpotifyUser.get(id=playlist.owner.id) or SpotifyUser(
            id=playlist.owner.id, name=playlist.owner.get("display_name") or ""
        )
        fields = {
            "id": playlist.id,
            "collaborative": playlist.collaborative,
            "name": playlist.name,
            "owner": owner,
            "public": playlist.public,
            "snapshot_id": playlist.snapshot_id,
            "tracks": playlist.tracks.total,
            "christmas": (
                "Pine Needle" in playlist.name or "christmas" in playlist.name.lower()
            ),
            "meta": playlist.name.startswith("Meta"),
            "images": [Image.get(url=im.url) or Image(**im) for im in playlist.images],
        }
        for pattern in cls.PATTERNS.values():
            match = pattern.match(playlist.name)
            if match:
                groups = match.groupdict()
                fields.update(cls.get_fields(groups))
                break

        else:
            logger.warning("No pattern matches the playlist: %s", playlist.name)

        if fields.get("country"):
            fields["country"] = Country.from_str(fields["country"])
        if fields.get("city"):
            fields["city"] = City.get(name=fields["city"]) or (
                fields["country"]
                and City(name=fields["city"], country=fields["country"])
            )
        if fields.get("genre"):
            fields["genre"] = Genre.get(name=fields["genre"]) or Genre(
                name=fields["genre"]
            )
        return cls(**fields)


class Artist(db.Entity, ImageMixin):
    _table_ = "artists"
    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
    name = Required(str, index=True)
    followers = Required(int)
    genres = Set(Genre)
    fans = Set(User, reverse="top_artists", table="artist_fans")
    haters = Set(User, reverse="disliked_artists", table="artist_haters")
    popularity = Optional(int, sql_default="0")
    images = Set(Image, cascade_delete=True)

    def play(self, client, device=None):
        return client.start_playback(artist=self.uri, device=device)

    @property
    def uri(self):
        return f"spotify:artist:{self.id}"

    @property
    def href(self):
        return f"https://api.spotify.com/v1/artists/{self.id}"

    @property
    def external_url(self):
        return f"http://open.spotify.com/artist/{self.id}"

    @classmethod
    async def from_dict_async(cls, artist):
        if artist.images:
            try:
                color = await Image.grab_color_async(artist.images[-1].url)
            except:
                color = "#000000"
            for image in artist.images:
                image.color = color
        return cls.from_dict(artist, grab_image_color=False)

    @classmethod
    def from_dict(cls, artist, grab_image_color=True):
        if artist.images and grab_image_color:
            try:
                color = Image.grab_color(artist.images[-1].url)
            except:
                color = "#000000"
            for image in artist.images:
                image.color = color
        genres = [Genre.get(name=genre) or Genre(name=genre) for genre in artist.genres]
        images = [Image.get(url=image.url) or Image(**image) for image in artist.images]
        return cls(
            id=artist.id,
            name=artist.name,
            followers=artist.followers.total,
            genres=genres,
            images=images,
            popularity=artist.popularity,
        )


# pylint: disable=too-few-public-methods


class AudioFeatures(db.Entity):
    _table_ = "audio_features"
    KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
    acousticness = Required(float, min=0.0, max=1.0)
    danceability = Required(float, min=0.0, max=1.0)
    duration_ms = Required(int, min=0)
    energy = Required(float, min=0.0, max=1.0)
    instrumentalness = Required(float, min=0.0, max=1.0)
    key = Required(int, min=0, max=11)
    liveness = Required(float, min=0.0, max=1.0)
    loudness = Required(float, min=-60.0, max=0.0)
    mode = Required(bool)
    speechiness = Required(float, min=0.0, max=1.0)
    tempo = Required(float, min=0, max=1000)
    time_signature = Required(int)
    valence = Required(float, min=0.0, max=1.0)

    # pylint: disable=arguments-differ,signature-differs
    def to_dict(self, *args, **kwargs):
        _dict = super().to_dict(*args, **kwargs)
        if "mode" in _dict:
            _dict["mode"] = int(_dict["mode"])
        return _dict

    @classmethod
    def from_dict(cls, track):
        return cls(
            id=track["id"],
            acousticness=track["acousticness"],
            danceability=track["danceability"],
            duration_ms=track["duration_ms"],
            energy=track["energy"],
            instrumentalness=track["instrumentalness"],
            key=track["key"],
            liveness=track["liveness"],
            loudness=track["loudness"],
            mode=bool(track["mode"]),
            speechiness=track["speechiness"],
            tempo=track["tempo"],
            time_signature=track["time_signature"],
            valence=track["valence"],
        )


if config.database.connection.filename:
    config.database.connection.filename = os.path.expandvars(
        config.database.connection.filename
    )
db.bind(**config.database.connection)

GENERATE_MAPPING = os.getenv("SPFY_GENERATE_MAPPING")
if GENERATE_MAPPING not in {"false", "0", "off", "f", "no"} and (
    config.database.generate_mapping
    or GENERATE_MAPPING in {"true", "1", "on", "t", "yes"}
):
    db.generate_mapping(create_tables=True)
