# coding: utf-8
# pylint: disable=too-many-lines,too-many-public-methods
from datetime import datetime
from functools import lru_cache, partialmethod
from itertools import chain
from operator import attrgetter
from time import sleep

import ujson as json
from first import first

from . import logger
from .cache import AudioFeatures, Playlist, db, db_session, select
from .constants import (
    API,
    DEVICE_ID_RE,
    MANELISTI,
    PLAYLIST_URI_RE,
    AudioFeature,
    TimeRange,
)
from .exceptions import (
    SpotifyAuthException,
    SpotifyDeviceUnavailableException,
    SpotifyException,
    SpotifyForbiddenException,
    SpotifyRateLimitException,
)
from .mixins import AuthMixin, EmailMixin
from .result import SpotifyResult


class SpotifyClient(AuthMixin, EmailMixin):
    def __init__(self, *args, proxies=None, requests_timeout=None, **kwargs):
        """
        Create a Spotify API object.

        :param proxies: Definition of proxies
        :param requests_timeout: Tell Requests to stop waiting for a response after a given number of seconds
        """
        super().__init__(*args, **kwargs)
        self.proxies = proxies
        self.requests_timeout = requests_timeout

    @db_session
    def _increment_api_call_count(self):
        try:
            user = self.user
        except Exception:
            logger.warning("Tried to use an inexistent user: %s", self.user_id)
        else:
            user.api_calls += 1
            user.last_usage_at = datetime.utcnow()

    @staticmethod
    def _check_response(response):
        try:
            response.raise_for_status()
        except Exception as exc:
            exception_params = SpotifyClient.get_exception_params(response)
            if response.status_code == 429 or (
                response.status_code >= 500 and response.status_code < 600
            ):
                raise SpotifyRateLimitException(
                    retry_after=int(response.headers.get("Retry-After", 0)),
                    **exception_params,
                ) from exc

            if response.status_code == 403:
                raise SpotifyForbiddenException(**exception_params) from exc

            raise SpotifyException(**exception_params) from exc

    @staticmethod
    def get_exception_params(response):
        return {
            "status_code": response.status_code,
            "url": response.url,
            "headers": response.headers,
            "text": response.text,
        }

    def _internal_call(
        self, method, url, payload, params, headers=None, retries=0, check_202=False
    ):
        logger.debug(url)
        if payload and not isinstance(payload, (bytes, str)):
            payload = json.dumps(payload)
        r = self.session.request(
            method,
            url,
            proxies=self.proxies,
            timeout=self.requests_timeout,
            headers={"Content-Type": "application/json", **(headers or {})},
            data=payload,
            params={k: v for k, v in params.items() if v is not None},
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        logger.debug("HTTP Status Code: {r.status_code}")
        logger.debug("%s: %s", method, r.url)
        if payload and not isinstance(payload, bytes):
            logger.debug("DATA: %s", payload)

        if check_202 and r.status_code == 202:
            if retries > 0:
                logger.warning(
                    "Device is temporarily unavailable. Retrying in 5 seconds..."
                )
                sleep(5)
                return self._internal_call(
                    method, url, payload, params, headers, retries=retries - 1
                )

            exception_params = self.get_exception_params(r)
            raise SpotifyDeviceUnavailableException(**exception_params)

        try:
            self._check_response(r)
        except SpotifyRateLimitException as exc:
            logger.warning(
                "Reached API rate limit. Retrying in %s seconds...", exc.retry_after
            )
            sleep(exc.retry_after)
            return self._internal_call(method, url, payload, params)

        if self.user_id:
            self._increment_api_call_count()
        if r.text and r.text != "null":
            results = r.json()
            logger.debug("RESP: %s", r.text)
            return SpotifyResult(results, _client=self)

        return None

    def _api_call(self, method, url, args=None, payload=None, headers=None, **kwargs):
        if not self.is_authenticated:
            raise SpotifyAuthException

        retries = kwargs.pop("retries", 0)
        check_202 = kwargs.pop("check_202", False)
        if args:
            kwargs.update(args)

        if "device_id" in kwargs:
            try:
                kwargs["device_id"] = self.get_device_id(kwargs["device_id"])
            except ValueError as e:
                logger.exception(e)

        if not url.startswith("http"):
            url = API.PREFIX.value + url
        return self._internal_call(
            method, url, payload, kwargs, headers, retries, check_202
        )

    def _get(self, url, args=None, payload=None, **kwargs):
        return self._api_call("GET", url, args, payload, **kwargs)

    def _post(self, url, args=None, payload=None, **kwargs):
        return self._api_call("POST", url, args, payload, **kwargs)

    def _delete(self, url, args=None, payload=None, **kwargs):
        return self._api_call("DELETE", url, args, payload, **kwargs)

    def _put(self, url, args=None, payload=None, **kwargs):
        return self._api_call("PUT", url, args, payload, **kwargs)

    def previous(self, result, **kwargs):
        """returns the previous result given a paged result

        Parameters:
            - result - a previously returned paged result
        """
        if result["previous"]:
            return self._get(result["previous"], **kwargs)

        return None

    def track(self, track_id, **kwargs):
        """returns a single track given the track's ID, URI or URL

        Parameters:
            - track_id - a spotify URI, URL or ID
        """
        _id = self._get_track_id(track_id)
        # pylint: disable=no-member
        return self._get(API.TRACK.value.format(id=_id), **kwargs)

    def tracks(self, tracks, market="from_token", **kwargs):
        """returns a list of tracks given a list of track IDs, URIs, or URLs

        Parameters:
            - tracks - a list of spotify URIs, URLs or IDs
            - market - an ISO 3166-1 alpha-2 country code.
        """
        track_list = map(self._get_track_id, tracks)
        return self._get(
            API.TRACKS.value, ids=",".join(track_list), market=market, **kwargs
        )

    def artist(self, artist_id, **kwargs):
        """returns a single artist given the artist's ID, URI or URL

        Parameters:
            - artist_id - an artist ID, URI or URL
        """
        _id = self._get_artist_id(artist_id)
        # pylint: disable=no-member
        return self._get(API.ARTIST.value.format(id=_id), **kwargs)

    def artists(self, artists, **kwargs):
        """returns a list of artists given the artist IDs, URIs, or URLs

        Parameters:
            - artists - a list of  artist IDs, URIs or URLs
        """
        artist_list = map(self._get_artist_id, artists)
        return self._get(API.ARTISTS.value, ids=",".join(artist_list), **kwargs)

    def artist_albums(
        self, artist_id, album_type=None, country=None, limit=20, offset=0, **kwargs
    ):
        """Get Spotify catalog information about an artist's albums

        Parameters:
            - artist_id - the artist ID, URI or URL
            - album_type - 'album', 'single', 'appears_on', 'compilation'
            - country - limit the response to one particular country.
            - limit  - the number of albums to return
            - offset - the index of the first album to return
        """
        _id = self._get_artist_id(artist_id)
        return self._get(
            API.ARTIST_ALBUMS.value.format(id=_id),  # pylint: disable=no-member
            album_type=album_type,
            country=country,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def artist_top_tracks(self, artist_id, country="US", **kwargs):
        """Get Spotify catalog information about an artist's top 10 tracks
        by country.

        Parameters:
            - artist_id - the artist ID, URI or URL
            - country - limit the response to one particular country.
        """
        _id = self._get_artist_id(artist_id)
        # pylint: disable=no-member
        return self._get(
            API.ARTIST_TOP_TRACKS.value.format(id=_id), country=country, **kwargs
        )

    @lru_cache(maxsize=128)
    def artist_related_artists(self, artist_id, **kwargs):
        """Get Spotify catalog information about artists similar to an
        identified artist. Similarity is based on analysis of the
        Spotify community's listening history.

        Parameters:
            - artist_id - the artist ID, URI or URL
        """
        _id = self._get_artist_id(artist_id)
        # pylint: disable=no-member
        return self._get(API.ARTIST_RELATED_ARTISTS.value.format(id=_id), **kwargs)

    def album(self, album_id, **kwargs):
        """returns a single album given the album's ID, URIs or URL

        Parameters:
            - album_id - the album ID, URI or URL
        """
        _id = self._get_album_id(album_id)
        # pylint: disable=no-member
        return self._get(API.ALBUM.value.format(id=_id), **kwargs)

    def album_tracks(self, album_id, limit=50, offset=0, **kwargs):
        """Get Spotify catalog information about an album's tracks

        Parameters:
            - album_id - the album ID, URI or URL
            - limit  - the number of items to return
            - offset - the index of the first item to return
        """
        _id = self._get_album_id(album_id)
        # pylint: disable=no-member
        return self._get(
            API.ALBUM_TRACKS.value.format(id=_id), limit=limit, offset=offset, **kwargs
        )

    def albums(self, albums, **kwargs):
        """returns a list of albums given the album IDs, URIs, or URLs

        Parameters:
            - albums - a list of  album IDs, URIs or URLs
        """
        album_list = map(self._get_album_id, albums)
        return self._get(API.ALBUMS.value, ids=",".join(album_list), **kwargs)

    def search(self, url, q, limit=10, offset=0, market="from_token", **kwargs):
        """searches for an item

        Parameters:
            - q - the search query
            - limit  - the number of items to return
            - offset - the index of the first item to return
            - type - the type of item to return. One of 'artist', 'album',
                     'track' or 'playlist'
            - market - An ISO 3166-1 alpha-2 country code or the string from_token.
        """
        return self._get(url, q=q, limit=limit, offset=offset, market=market, **kwargs)

    def search_track(self, track, limit=10, offset=0, market="from_token", **kwargs):
        return self.search(
            API.SEARCH_TRACK.value,
            track,
            limit=limit,
            offset=offset,
            market=market,
            **kwargs,
        )

    def search_album(self, album, limit=10, offset=0, market="from_token", **kwargs):
        return self.search(
            API.SEARCH_ALBUM.value,
            album,
            limit=limit,
            offset=offset,
            market=market,
            **kwargs,
        )

    def search_artist(self, artist, limit=10, offset=0, market="from_token", **kwargs):
        return self.search(
            API.SEARCH_ARTIST.value,
            artist,
            limit=limit,
            offset=offset,
            market=market,
            **kwargs,
        )

    def search_playlist(
        self, playlist, limit=10, offset=0, market="from_token", **kwargs
    ):
        return self.search(
            API.SEARCH_PLAYLIST.value,
            playlist,
            limit=limit,
            offset=offset,
            market=market,
            **kwargs,
        )

    def profile(self, user, **kwargs):
        """Gets basic profile information about a Spotify User

        Parameters:
            - user - the id of the user
        """
        # pylint: disable=no-member
        return self._get(API.USER.value.format(user_id=user), **kwargs)

    def current_user_playlists(self, limit=50, offset=0, **kwargs):
        """Get current user playlists without required getting his profile
        Parameters:
            - limit  - the number of items to return
            - offset - the index of the first item to return
        """
        return self._get(API.MY_PLAYLISTS.value, limit=limit, offset=offset, **kwargs)

    def user_playlists(self, user, limit=50, offset=0, **kwargs):
        """Gets playlists of a user

        Parameters:
            - user - the id of the usr
            - limit  - the number of items to return
            - offset - the index of the first item to return
        """
        # pylint: disable=no-member
        return self._get(
            API.PLAYLISTS.value.format(user_id=user),
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def user_playlist(
        self, user, playlist_id=None, fields=None, market="from_token", **kwargs
    ):
        """Gets playlist of a user
        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - fields - which fields to return
        """
        if playlist_id is None:
            return self._get("users/%s/starred" % (user), fields=fields, **kwargs)

        _id = self._get_playlist_id(playlist_id)
        # pylint: disable=no-member
        return self._get(
            API.PLAYLIST.value.format(user_id=user, playlist_id=_id),
            fields=fields,
            market=market,
            **kwargs,
        )

    def user_playlist_tracks(
        self,
        user,
        playlist_id=None,
        fields=None,
        limit=100,
        offset=0,
        market="from_token",
        **kwargs,
    ):
        """Get full details of the tracks of a playlist owned by a user.

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - fields - which fields to return
            - limit - the maximum number of tracks to return
            - offset - the index of the first track to return
            - market - an ISO 3166-1 alpha-2 country code.
        """
        _id = self._get_playlist_id(playlist_id)
        # pylint: disable=no-member
        return self._get(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id),
            limit=limit,
            offset=offset,
            fields=fields,
            market=market,
            **kwargs,
        )

    def user_playlist_create(self, user, name, public=True, description="", **kwargs):
        """Creates a playlist for a user

        Parameters:
            - user - the id of the user
            - name - the name of the playlist
            - public - is the created playlist public
            - description - the description of the playlist
        """
        # pylint: disable=no-member
        data = {"name": name, "public": public, "description": description}
        return self._post(
            API.PLAYLISTS.value.format(user_id=user), payload=data, **kwargs
        )

    def user_playlist_upload_cover_image(self, user, playlist_id, image, **kwargs):
        """Creates a playlist for a user

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - image - base64 encoded image
        """
        # pylint: disable=no-member
        return self._put(
            API.PLAYLIST_IMAGES.value.format(user_id=user, playlist_id=playlist_id),
            payload=image,
            headers={"Content-Type": "image/jpeg"},
            **kwargs,
        )

    def user_playlist_change_details(
        self,
        user,
        playlist_id,
        name=None,
        public=None,
        collaborative=None,
        description=None,
        **kwargs,
    ):
        """Changes a playlist's name and/or public/private state

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - name - optional name of the playlist
            - public - optional is the playlist public
            - collaborative - optional is the playlist collaborative
            - description - the description of the playlist
        """
        data = {}
        if isinstance(name, str):
            data["name"] = name
        if isinstance(public, bool):
            data["public"] = public
        if isinstance(collaborative, bool):
            data["collaborative"] = collaborative
        if isinstance(collaborative, str):
            data["description"] = description
        # pylint: disable=no-member
        return self._put(
            API.PLAYLIST.value.format(user_id=user, playlist_id=playlist_id),
            payload=data,
            **kwargs,
        )

    def user_playlist_unfollow(self, user, playlist_id, **kwargs):
        """Unfollows (deletes) a playlist for a user

        Parameters:
            - user - the id of the user
            - name - the name of the playlist
        """
        return self._delete(
            "users/%s/playlists/%s/followers" % (user, playlist_id), **kwargs
        )

    def user_playlist_add_tracks(
        self, user, playlist_id, tracks, position=None, **kwargs
    ):
        """Adds tracks to a playlist

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - tracks - a list of track URIs, URLs or IDs
            - position - the position to add the tracks
        """
        _id = self._get_playlist_id(playlist_id)
        # pylint: disable=no-member
        url = API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id)
        track_uris = list(map(self._get_track_uri, tracks))
        if len(track_uris) <= 100:
            return self._post(
                url, payload={"uris": track_uris}, position=position, **kwargs
            )

        batches = [
            {"uris": track_uris[i : i + 100]} for i in range(0, len(track_uris), 100)
        ]
        results = [
            self._post(
                url,
                payload=t,
                position=(None if position is None else i * 100 + position),
                **kwargs,
            )
            for i, t in enumerate(batches)
        ]
        return results

    def user_playlist_replace_tracks(self, user, playlist_id, tracks, **kwargs):
        """Replace all tracks in a playlist

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - tracks - the list of track ids to add to the playlist
        """
        _id = self._get_playlist_id(playlist_id)
        # pylint: disable=no-member
        url = API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id)
        first_100_tracks, rest_tracks = tracks[:100], tracks[100:]
        track_uris = list(map(self._get_track_uri, first_100_tracks))
        replaced = self._put(url, payload={"uris": track_uris}, **kwargs)
        if not rest_tracks:
            return replaced

        added = self.user_playlist_add_tracks(user, playlist_id, rest_tracks)
        if isinstance(added, list):
            return [replaced, *added]

        return [replaced, added]

    def user_playlist_reorder_tracks(
        self,
        user,
        playlist_id,
        range_start,
        insert_before,
        range_length=1,
        snapshot_id=None,
        **kwargs,
    ):
        """Reorder tracks in a playlist

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - range_start - the position of the first track to be reordered
            - range_length - optional the number of tracks to be reordered (default: 1)
            - insert_before - the position where the tracks should be inserted
            - snapshot_id - optional playlist's snapshot ID
        """
        _id = self._get_playlist_id(playlist_id)
        payload = {
            "range_start": range_start,
            "range_length": range_length,
            "insert_before": insert_before,
        }
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        # pylint: disable=no-member
        return self._put(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id),
            payload=payload,
            **kwargs,
        )

    def user_playlist_remove_all_occurrences_of_tracks(
        self, user, playlist_id, tracks, snapshot_id=None, **kwargs
    ):
        """Removes all occurrences of the given tracks from the given playlist

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - tracks - the list of track ids to add to the playlist
            - snapshot_id - optional id of the playlist snapshot

        """
        _id = self._get_playlist_id(playlist_id)
        track_uris = map(self._get_track_uri, tracks)
        payload = {"tracks": [{"uri": track} for track in track_uris]}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        # pylint: disable=no-member
        return self._delete(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id),
            payload=payload,
            **kwargs,
        )

    def user_playlist_remove_specific_occurrences_of_tracks(
        self, user, playlist_id, tracks, snapshot_id=None, **kwargs
    ):
        """Removes all occurrences of the given tracks from the given playlist

        Parameters:
            - user - the id of the user
            - playlist_id - the id of the playlist
            - tracks - an array of objects containing Spotify URIs of the tracks
                       to remove with their current positions in the playlist.
                For example:
                    [
                      { "uri":"4iV5W9uYEdYUVa79Axb7Rh", "positions":[2] },
                      { "uri":"1301WleyT98MSxVHPZCA6M", "positions":[7] }
                    ]
            - snapshot_id - optional id of the playlist snapshot
        """
        _id = self._get_playlist_id(playlist_id)
        ftracks = []
        for tr in tracks:
            ftracks.append(
                {"uri": self._get_uri("track", tr["uri"]), "positions": tr["positions"]}
            )
        payload = {"tracks": ftracks}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        # pylint: disable=no-member
        return self._delete(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=_id),
            payload=payload,
            **kwargs,
        )

    def user_playlist_follow_playlist(self, playlist_owner_id, playlist_id, **kwargs):
        """
        Add the current authenticated user as a follower of a playlist.

        Parameters:
            - playlist_owner_id - the user id of the playlist owner
            - playlist_id - the id of the playlist

        """
        return self._put(
            API.PLAYLIST_FOLLOWERS.value.format(  # pylint: disable=no-member
                owner_id=playlist_owner_id, playlist_id=playlist_id
            ),
            **kwargs,
        )

    def user_playlist_is_following(
        self, playlist_owner_id, playlist_id, user_ids, **kwargs
    ):
        """
        Check to see if the given users are following the given playlist

        Parameters:
            - playlist_owner_id - the user id of the playlist owner
            - playlist_id - the id of the playlist
            - user_ids - the ids of the users that you want to check to see if they follow the playlist. Maximum: 5 ids.

        """
        return self._get(
            API.PLAYLIST_FOLLOWERS_CONTAINS.value.format(  # pylint: disable=no-member
                user_id=playlist_owner_id, playlist_id=playlist_id
            ),
            ids=",".join(user_ids),
            **kwargs,
        )

    def me(self, **kwargs):
        """Get detailed profile information about the current user.
        An alias for the 'current_user' method.
        """
        return self._get(API.ME.value, **kwargs)

    def current_user(self, **kwargs):
        """Get detailed profile information about the current user.
        An alias for the 'me' method.
        """
        return self.me(**kwargs)

    def current_user_saved_albums(self, limit=20, offset=0, **kwargs):
        """Gets a list of the albums saved in the current authorized user's
        "Your Music" library

        Parameters:
            - limit - the number of albums to return
            - offset - the index of the first album to return

        """
        return self._get(API.MY_ALBUMS.value, limit=limit, offset=offset, **kwargs)

    def current_user_saved_tracks(self, limit=20, offset=0, **kwargs):
        """Gets a list of the tracks saved in the current authorized user's
        "Your Music" library

        Parameters:
            - limit - the number of tracks to return
            - offset - the index of the first track to return

        """
        return self._get(API.MY_TRACKS.value, limit=limit, offset=offset, **kwargs)

    def current_user_followed_artists(self, limit=20, after=None, **kwargs):
        """Gets a list of the artists followed by the current authorized user

        Parameters:
            - limit - the number of tracks to return
            - after - ghe last artist ID retrieved from the previous request

        """
        return self._get(
            API.MY_FOLLOWING.value, type="artist", limit=limit, after=after, **kwargs
        )

    def user_follow_artists(self, ids=None, **kwargs):
        """Follow one or more artists
        Parameters:
            - ids - a list of artist IDs
        """
        return self._put(
            API.MY_FOLLOWING.value, type="artist", ids=",".join(ids or []), **kwargs
        )

    def user_follow_users(self, ids=None, **kwargs):
        """Follow one or more users
        Parameters:
            - ids - a list of user IDs
        """
        return self._put(
            API.MY_FOLLOWING.value, type="user", ids=",".join(ids or []), **kwargs
        )

    def current_user_saved_tracks_delete(self, tracks=None, **kwargs):
        """Remove one or more tracks from the current user's
        "Your Music" library.

        Parameters:
            - tracks - a list of track URIs, URLs or IDs
        """
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._delete(API.MY_TRACKS.value, ids=",".join(track_list), **kwargs)

    def current_user_saved_tracks_contains(self, tracks=None, **kwargs):
        """Check if one or more tracks is already saved in
        the current Spotify user’s “Your Music” library.

        Parameters:
            - tracks - a list of track URIs, URLs or IDs
        """
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._get(API.MY_TRACKS_CONTAINS.value, ",".join(track_list), **kwargs)

    def current_user_saved_tracks_add(self, tracks=None, **kwargs):
        """Add one or more tracks to the current user's
        "Your Music" library.

        Parameters:
            - tracks - a list of track URIs, URLs or IDs
        """
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._put(API.MY_TRACKS.value, ids=",".join(track_list), **kwargs)

    def current_user_top_artists(
        self, limit=20, offset=0, time_range=TimeRange.MEDIUM_TERM, **kwargs
    ):
        """Get the current user's top artists

        Parameters:
            - limit - the number of entities to return
            - offset - the index of the first entity to return
            - time_range - Over what time frame are the affinities computed
              Valid-values: short_term, medium_term, long_term
        """
        return self._get(
            API.MY_TOP.value.format(type="artists"),  # pylint: disable=no-member
            time_range=TimeRange(time_range).value,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def current_user_top_tracks(
        self, limit=20, offset=0, time_range=TimeRange.MEDIUM_TERM, **kwargs
    ):
        """Get the current user's top tracks

        Parameters:
            - limit - the number of entities to return
            - offset - the index of the first entity to return
            - time_range - Over what time frame are the affinities computed
              Valid-values: short_term, medium_term, long_term
        """
        return self._get(
            API.MY_TOP.value.format(type="tracks"),  # pylint: disable=no-member
            time_range=TimeRange(time_range).value,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def current_user_saved_albums_add(self, albums=None, **kwargs):
        """Add one or more albums to the current user's
        "Your Music" library.
        Parameters:
            - albums - a list of album URIs, URLs or IDs
        """
        album_list = map(self._get_album_id, albums or [])
        return self._put(API.MY_ALBUMS.value, ids=",".join(album_list), **kwargs)

    def featured_playlists(
        self, locale=None, country=None, timestamp=None, limit=20, offset=0, **kwargs
    ):
        """Get a list of Spotify featured playlists

        Parameters:
            - locale - The desired language, consisting of a lowercase ISO
              639 language code and an uppercase ISO 3166-1 alpha-2 country
              code, joined by an underscore.

            - country - An ISO 3166-1 alpha-2 country code.

            - timestamp - A timestamp in ISO 8601 format:
              yyyy-MM-ddTHH:mm:ss. Use this parameter to specify the user's
              local time to get results tailored for that specific date and
              time in the day

            - limit - The maximum number of items to return. Default: 20.
              Minimum: 1. Maximum: 50

            - offset - The index of the first item to return. Default: 0
              (the first object). Use with limit to get the next set of
              items.
        """
        return self._get(
            API.FEATURED_PLAYLISTS.value,
            locale=locale,
            country=country,
            timestamp=timestamp,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def new_releases(self, country=None, limit=20, offset=0, **kwargs):
        """Get a list of new album releases featured in Spotify

        Parameters:
            - country - An ISO 3166-1 alpha-2 country code.

            - limit - The maximum number of items to return. Default: 20.
              Minimum: 1. Maximum: 50

            - offset - The index of the first item to return. Default: 0
              (the first object). Use with limit to get the next set of
              items.
        """
        return self._get(
            API.NEW_RELEASES.value,
            country=country,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def categories(self, country=None, locale=None, limit=20, offset=0, **kwargs):
        """Get a list of new album releases featured in Spotify

        Parameters:
            - country - An ISO 3166-1 alpha-2 country code.
            - locale - The desired language, consisting of an ISO 639
              language code and an ISO 3166-1 alpha-2 country code, joined
              by an underscore.

            - limit - The maximum number of items to return. Default: 20.
              Minimum: 1. Maximum: 50

            - offset - The index of the first item to return. Default: 0
              (the first object). Use with limit to get the next set of
              items.
        """
        return self._get(
            API.CATEGORIES.value,
            country=country,
            locale=locale,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def category_playlists(
        self, category_id=None, country=None, limit=20, offset=0, **kwargs
    ):
        """Get a list of new album releases featured in Spotify

        Parameters:
            - category_id - The Spotify category ID for the category.

            - country - An ISO 3166-1 alpha-2 country code.

            - limit - The maximum number of items to return. Default: 20.
              Minimum: 1. Maximum: 50

            - offset - The index of the first item to return. Default: 0
              (the first object). Use with limit to get the next set of
              items.
        """
        # pylint: disable=no-member
        return self._get(
            API.CATEGORY_PLAYLISTS.value.format(id=category_id),
            country=country,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    # pylint: disable=too-many-locals
    def recommendations(
        self,
        seed_artists=None,
        seed_genres=None,
        seed_tracks=None,
        limit=20,
        country="from_token",
        filter_manele=True,
        **kwargs,
    ):
        """Get a list of recommended tracks for one to five seeds.

        Parameters:
            - seed_artists - a list of artist IDs, URIs or URLs

            - seed_tracks - a list of artist IDs, URIs or URLs

            - seed_genres - a list of genre names. Available genres for
              recommendations can be found by calling recommendation_genre_seeds

            - country - An ISO 3166-1 alpha-2 country code. If provided, all
              results will be playable in this country.

            - limit - The maximum number of items to return. Default: 20.
              Minimum: 1. Maximum: 100

            - min/max/target_<attribute> - For the tuneable track attributes listed
              in the documentation, these values provide filters and targeting on
              results.
        """
        params = dict(limit=limit)
        if seed_artists:
            params["seed_artists"] = ",".join(map(self._get_artist_id, seed_artists))
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres)
        if seed_tracks:
            params["seed_tracks"] = ",".join(map(self._get_track_id, seed_tracks))
        if country:
            params["market"] = country
        for attribute in list(AudioFeature):
            for prefix in ["min_", "max_", "target_"]:
                param = prefix + attribute.value
                if param in kwargs:
                    params[param] = kwargs.pop(param)

        if not filter_manele:
            return self._get(API.RECOMMENDATIONS.value, **params, **kwargs)

        for _ in range(5):
            result = self._get(API.RECOMMENDATIONS.value, **params, **kwargs)
            tracks = [
                t
                for t in result.tracks
                if not any(
                    "manele" in (a.genres or []) or a.id in MANELISTI for a in t.artists
                )
            ]
            if tracks:
                result.tracks = tracks
                return result
        return self._get(API.RECOMMENDATIONS.value, **params, **kwargs)

    def recommendation_genre_seeds(self, **kwargs):
        """Get a list of genres available for the recommendations function."""
        return self._get(API.RECOMMENDATIONS_GENRES.value, **kwargs)

    def audio_analysis(self, track=None, **kwargs):
        """Get audio analysis for a track based upon its Spotify ID
        Parameters:
            - track - a track URI, URL or ID
        """
        _id = self._get_track_id(track)
        # pylint: disable=no-member
        return self._get(API.AUDIO_ANALYSIS.value.format(id=_id), **kwargs)

    def audio_features(self, track=None, tracks=None, with_cache=True, **kwargs):
        """Get audio features for one or multiple tracks based upon their Spotify IDs
        Parameters:
            - track - a track URI, URL or ID
            - tracks - a list of track URIs, URLs or IDs, maximum: 100 ids
        """
        if track:
            _id = self._get_track_id(track)
            # pylint: disable=no-member
            return self._get(API.AUDIO_FEATURES_SINGLE.value.format(id=_id), **kwargs)

        tracks = list(map(self._get_track_id, tracks or []))
        cached_tracks = []
        if with_cache:
            with db_session:
                cached_tracks = select(a for a in AudioFeatures if a.id in tracks)[:]
                tracks = list(set(tracks) - {a.id for a in cached_tracks})
        batches = [tracks[i : i + 100] for i in range(0, len(tracks), 100)]
        audio_features = [
            self._get(API.AUDIO_FEATURES_MULTIPLE.value, ids=",".join(t), **kwargs)
            for t in batches
        ]
        with db_session:
            audio_features = [
                AudioFeatures.from_dict(t) for t in chain.from_iterable(audio_features)
            ] + cached_tracks
        return audio_features

    def devices(self, **kwargs):
        """Get a list of user's available devices."""
        return self._get(API.DEVICES.value, check_202=True, **kwargs)

    def get_device_id(self, device=None):
        if isinstance(device, (str, bytes)) and DEVICE_ID_RE.match(device):
            return device

        return self.get_device(device).id

    def get_device(self, device=None, only_active=True):
        """Get Spotify device based on name

        :param str, optional device: device name or ID
        :param str, optional field: device attribute to return

        str or dict: Spotify device
        """
        devices = self.devices().devices
        device_names = ", ".join([d.name for d in devices])
        device_name_or_id = device
        if not device_name_or_id:
            if only_active:
                device = first(devices, key=attrgetter("is_active"))
                if not device:
                    raise ValueError(
                        f"""
            There's no active device.
            Possible devices: {device_names}"""
                    )
            else:
                device = first(devices, key=attrgetter("is_active")) or first(devices)
        else:
            device = first(devices, key=lambda d: device_name_or_id in (d.name, d.id))
            if not device:
                raise ValueError(
                    f"""
        Device {device_name_or_id} doesn't exist.
        Possible devices: {device_names}"""
                )

        return device

    def current_playback(self, market="from_token", **kwargs):
        """Get information about user's current playback.

        Parameters:
            - market - an ISO 3166-1 alpha-2 country code.
        """
        return self._get(API.PLAYER.value, market=market, **kwargs)

    def current_user_recently_played(self, limit=50, **kwargs):
        """Get the current user's recently played tracks

        Parameters:
            - limit - the number of entities to return
        """
        return self._get(API.RECENTLY_PLAYED.value, limit=limit, **kwargs)

    def currently_playing(self, market="from_token", **kwargs):
        """Get user's currently playing track.

        Parameters:
            - market - an ISO 3166-1 alpha-2 country code.
        """
        return self._get(
            API.CURRENTLY_PLAYING.value, market=market, check_202=True, **kwargs
        )

    def transfer_playback(self, device, force_play=True, **kwargs):
        """Transfer playback to another device.
        Note that the API accepts a list of device ids, but only
        actually supports one.

        Parameters:
            - device - transfer playback to this device
            - force_play - true: after transfer, play. false:
                           keep current state.
        """
        device_id = self.get_device_id(device)
        data = {"device_ids": [device_id], "play": force_play}
        return self._put(API.PLAYER.value, payload=data, check_202=True, **kwargs)

    def start_playback(
        self,
        device=None,
        artist=None,
        album=None,
        playlist=None,
        tracks=None,
        offset=None,
        **kwargs,
    ):
        """Start or resume user's playback.

        Parameters:
            - device - device target for playback
            - playlist - spotify playlist to play
            - artist - spotify artist to play
            - album - spotify album to play
            - tracks - spotify tracks to play
            - offset - offset into context by index or track
        """
        data = {}
        if playlist:
            data["context_uri"] = self._get_playlist_uri(playlist)
        elif album:
            data["context_uri"] = self._get_album_uri(album)
        elif artist:
            data["context_uri"] = self._get_artist_uri(artist)
        elif tracks:
            data["uris"] = list(map(self._get_track_uri, tracks))
        if isinstance(offset, int):
            data["offset"] = dict(position=offset)
        elif isinstance(offset, str):
            data["offset"] = dict(uri=offset)
        return self._put(
            API.PLAY.value, device_id=device, payload=data, check_202=True, **kwargs
        )

    def pause_playback(self, device=None, **kwargs):
        """Pause user's playback.

        Parameters:
            - device - device target for playback
        """
        return self._put(API.PAUSE.value, device_id=device, check_202=True, **kwargs)

    def next_track(self, device=None, **kwargs):
        """Skip user's playback to next track.

        Parameters:
            - device - device target for playback
        """
        return self._post(API.NEXT.value, device_id=device, check_202=True, **kwargs)

    def previous_track(self, device=None, **kwargs):
        """Skip user's playback to previous track.

        Parameters:
            - device - device target for playback
        """
        return self._post(
            API.PREVIOUS.value, device_id=device, check_202=True, **kwargs
        )

    def seek_track(self, position_ms, device=None, **kwargs):
        """Seek to position in current track.

        Parameters:
            - position_ms - position in milliseconds to seek to
            - device - device target for playback
        """
        if not isinstance(position_ms, int):
            logger.warning("position_ms must be an integer")
            return None

        return self._put(
            API.SEEK.value,
            position_ms=position_ms,
            device_id=device,
            check_202=True,
            **kwargs,
        )

    def repeat(self, state, device=None, **kwargs):
        """Set repeat mode for playback.

        Parameters:
            - state - `track`, `context`, or `off`
            - device - device target for playback
        """
        if state not in ["track", "context", "off"]:
            logger.warning("Invalid state")
            return

        self._put(
            API.REPEAT.value, state=state, device_id=device, check_202=True, **kwargs
        )

    def volume(self, volume_percent: int = None, device: str = None, **kwargs):
        """Get or set playback volume.

        Parameters:
            - volume_percent - volume between 0 and 100
            - device - device target for playback
        """
        device = self.get_device(device)
        if volume_percent is None:
            return device.volume_percent

        assert 0 <= volume_percent <= 100
        return self._put(
            API.VOLUME.value,
            volume_percent=volume_percent,
            device_id=device.id,
            check_202=True,
            **kwargs,
        )

    def shuffle(self, state, device=None, **kwargs):
        """Toggle playback shuffling.

        Parameters:
            - state - true or false
            - device - device target for playback
        """
        if not isinstance(state, bool):
            logger.warning("State must be a boolean")
            return

        state = str(state).lower()
        self._put(
            API.SHUFFLE.value, state=state, device_id=device, check_202=True, **kwargs
        )

    @staticmethod
    def _get_id(_type, result):
        if isinstance(result, str):
            fields = result.split(":")
            if len(fields) >= 3:
                if _type != fields[-2]:
                    logger.warning(
                        "Expected id of type %s but found type %s %s",
                        _type,
                        fields[-2],
                        result,
                    )
                return fields[-1]

            fields = result.split("/")
            if len(fields) >= 3:
                itype = fields[-2]
                if _type != itype:
                    logger.warning(
                        "Expected id of type %s but found type %s %s",
                        _type,
                        itype,
                        result,
                    )
                return fields[-1]

        elif isinstance(result, (SpotifyResult, db.Entity)):
            return result.id

        elif isinstance(result, dict):
            return result["id"]

        return result

    _get_track_id = partialmethod(_get_id, "track")
    _get_artist_id = partialmethod(_get_id, "artist")
    _get_album_id = partialmethod(_get_id, "album")
    _get_playlist_id = partialmethod(_get_id, "playlist")

    def _get_uri(self, _type, result):
        return "spotify:" + _type + ":" + self._get_id(_type, result)

    def _get_playlist_uri(self, playlist, user=None):
        if isinstance(playlist, (str, bytes)) and PLAYLIST_URI_RE.match(playlist):
            return playlist

        if isinstance(playlist, Playlist):
            return playlist.uri

        if user is not None:
            return f'spotify:user:{self._get_id("user", user)}:playlist:{self._get_id("playlist", playlist)}'

        try:
            if "uri" in playlist:
                return playlist["uri"]

        except:
            pass

        return None

    _get_track_uri = partialmethod(_get_uri, "track")
    _get_artist_uri = partialmethod(_get_uri, "artist")
    _get_album_uri = partialmethod(_get_uri, "album")
