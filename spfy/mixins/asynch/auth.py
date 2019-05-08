import asyncio
import socket
import threading
import uuid
from datetime import datetime
from pathlib import Path

import addict
import aiohttp
import aiohttp.web
from aiohttp.web_runner import GracefulExit
from oauthlib.oauth2 import BackendApplicationClient
from pony.orm import db_session, get, select

from ... import config, logger, root
from ...cache import Country, User
from ...constants import API, AllScopes, AuthFlow
from ...exceptions import SpotifyCredentialsException
from ...sql import SQL
from .aiohttp_oauthlib import OAuth2Session

AUTH_HTML_FILE = root / "html" / "auth_message.html"
CACHE_FILE = Path.home() / ".cache" / "spfy" / ".web_cache"
web_app = aiohttp.web.Application()


def run_app(loop):
    asyncio.set_event_loop(loop)
    aiohttp.web.run_app(
        web_app, host="0.0.0.0", port=config.auth.callback.port, handle_signals=False
    )


class AuthMixin:
    def __init__(
        self,
        *args,
        client_id=None,
        client_secret=None,
        redirect_uri=None,
        user_id=None,
        username=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.client_id = client_id or config.app.client_id
        self.client_secret = client_secret or config.app.client_secret
        self.redirect_uri = self._get_redirect_uri(redirect_uri)
        self.user_id = user_id
        self.username = username
        self.callback_reached = threading.Event()
        self.flow = None
        self._session = None
        self.callback_loop = asyncio.new_event_loop()

    @property
    def session(self):
        return self._session

    @session.setter
    def session(self, new_session):
        if self._session and new_session != self._session:
            asyncio.ensure_future(self._session.close())
        self._session = new_session

    @staticmethod
    def _get_redirect_uri(redirect_uri):
        redirect_uri = (
            redirect_uri
            or config.app.redirect_uri
            or f"http://{socket.gethostname()}.local"
        )
        if config.auth.callback.enabled and config.auth.callback.port and redirect_uri:
            redirect_uri += f":{config.auth.callback.port}"
        return redirect_uri

    async def fetch_user(self, conn=None, op="OR", **fields):
        conn = conn or await self.dbpool

        if not (self.user_id or fields):
            return None

        user = None
        fields = {f: v for f, v in fields.items() if f}

        if self.user_id and not fields:
            user = await conn.fetchrow(SQL.user, self.user_id)
        else:
            condition = f" {op} ".join(
                f"{field} = ${i + 1}" for i, field in enumerate(fields.keys())
            )
            user = await conn.fetchrow(
                f"SELECT * FROM users WHERE {condition}", *fields.values()
            )

        if not user:
            return None

        return addict.Dict(dict(user))

    @property
    @db_session
    def user(self):
        return User[self.user_id]

    @property
    def is_authenticated(self):
        return bool(self.session and self.session.authorized)

    async def update_user_token(self, token):
        conn = await self.dbpool
        await conn.execute(SQL.update_user_token, token, self.user_id)

    # pylint: disable=too-many-locals
    async def authenticate_user_pg(
        self,
        username=None,
        email=None,
        code=None,
        state=None,
        auth_response=None,
        scope=AllScopes,
        conn=None,
    ):
        conn = conn or await self.dbpool

        self.flow = AuthFlow.AUTHORIZATION_CODE
        self.session = OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=scope,
            auto_refresh_url=API.TOKEN.value,
        )
        if self.user_id:
            user = await self.fetch_user()
            if user and user.token:
                self.session.token = user.token
                self.session.token_updater = self.update_user_token
                return user

        if username or email:
            user = await self.fetch_user(username=username, email=email)
            if user:
                self.user_id = user.id
                self.username = user.username
                self.session.token = user.token
                self.session.token_updater = self.update_user_token
                return user

        if code or auth_response:
            token = await self.session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=code,
                state=state,
                authorization_response=auth_response,
            )
            self.session.token_updater = self.update_user_token

            user_details = await self.current_user()
            if user_details.birthdate:
                birthdate = datetime.strptime(user_details.birthdate, "%Y-%m-%d")
            else:
                birthdate = None

            iso_country = Country.get_iso_country(user_details.country)
            if not iso_country:
                country_name = country_code = user_details.country
            else:
                country_name = iso_country.name
                country_code = iso_country.alpha_2

            new_user_id = self.user_id or uuid.uuid4()
            user = await conn.fetchrow(
                SQL.upsert_user,
                new_user_id,
                user_details.email or str(new_user_id),
                user_details.id or "",
                user_details.country or "",
                user_details.display_name or "",
                birthdate,
                token,
                user_details.product == "premium",
                country_code,
                country_name,
            )
            user = addict.Dict(dict(user))
            self.user_id = user.id
            self.username = user.username

            if user_details.images:
                await conn.executemany(
                    """INSERT INTO images (
                            url, height, width, "user", unsplash_id,
                            unsplash_user_fullname, unsplash_user_username
                        ) VALUES ($1, $2, $3, $4, '', '', '')
                        ON CONFLICT DO NOTHING""",
                    [
                        (i.url, i.height or None, i.width or None, user.id)
                        for i in user_details.images
                        if i.url
                    ],
                )
            return user

        return None

    async def authenticate_server_pg(self, conn=None):
        conn = conn or await self.dbpool

        self.flow = AuthFlow.CLIENT_CREDENTIALS

        USA = Country.get_iso_country("US")
        default_user = await conn.fetchrow(
            SQL.upsert_user,
            User.DEFAULT_USERID,
            User.DEFAULT_EMAIL,
            User.DEFAULT_USERNAME,
            USA.alpha_2,
            User.DEFAULT_USERNAME,
            None,
            {},
            False,
            USA.alpha_2,
            USA.name,
        )
        default_user = addict.Dict(dict(default_user))

        self.user_id = default_user.id
        self.username = default_user.username
        self.session = OAuth2Session(client=BackendApplicationClient(self.client_id))
        self.session.token_updater = self.update_user_token
        if default_user.token:
            self.session.token = default_user.token
        else:
            default_user.token = await self.session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        return self.session

    async def authenticate_user(
        self,
        username=None,
        email=None,
        code=None,
        state=None,
        auth_response=None,
        scope=AllScopes,
    ):
        self.flow = AuthFlow.AUTHORIZATION_CODE
        self.session = OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=scope,
            auto_refresh_url=API.TOKEN.value,
        )
        with db_session:
            if self.user_id:
                user = User.get(id=self.user_id)
                if user and user.token:
                    self.session.token = user.token
                    self.session.token_updater = User.token_updater(user.id)
                    return self.session

            if username or email:
                if username:
                    user = get(u for u in User if u.username == username)
                elif email:
                    user = get(u for u in User if u.email == email)
                if user:
                    self.user_id = user.id
                    self.username = user.username
                    self.session.token = user.token
                    self.session.token_updater = User.token_updater(user.id)
                    return self.session

            if code or auth_response:
                token = await self.session.fetch_token(
                    token_url=API.TOKEN.value,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    code=code,
                    state=state,
                    authorization_response=auth_response,
                )
                user_details = await self.current_user()
                user = (
                    select(
                        u
                        for u in User
                        if u.username == user_details.id
                        or u.email == user_details.email
                    )
                    .for_update()
                    .get()
                )
                if user:
                    user.token = token
                    if user.id != self.user_id:
                        self.user_id = user.id
                        self.username = user.username
                elif self.user_id:
                    user = User.get_for_update(id=self.user_id)
                    if user:
                        user.token = token
                if not user:
                    self.user_id = self.user_id or uuid.uuid4()
                    user_details["user_id"] = self.user_id
                    user_details["token"] = token
                    user = User.from_dict(user_details)
                    self.username = user.username
                return self.session

        return self.session

    @db_session
    async def authenticate_server(self):
        self.flow = AuthFlow.CLIENT_CREDENTIALS
        default_user = User.default()
        self.user_id = default_user.id
        self.username = default_user.username
        self.session = OAuth2Session(client=BackendApplicationClient(self.client_id))
        self.session.token_updater = User.token_updater(default_user.id)
        if default_user.token:
            self.session.token = default_user.token
        else:
            default_user.token = await self.session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        return self.session

    async def authenticate(self, flow=config.auth.flow, **auth_params):
        if not (self.client_id and self.client_secret):
            raise SpotifyCredentialsException

        self.flow = AuthFlow(flow)
        if self.flow == AuthFlow.CLIENT_CREDENTIALS:
            await self.authenticate_server()
        elif self.flow == AuthFlow.AUTHORIZATION_CODE:
            await self.authenticate_user(**auth_params)
            if not self.session.token:
                if config.auth.callback.enabled:
                    self.start_callback()
                authorization_url, _ = self.session.authorization_url(
                    API.AUTHORIZE.value
                )
                if config.auth.send_auth_url_to_email:
                    email = auth_params.get("email") or config.auth.email
                    self.send_auth_email(email, authorization_url)
                else:
                    print(f"Login here: {authorization_url}")
                await self.wait_for_authorization()

    async def wait_for_authorization(self):
        if not config.auth.callback.enabled:
            url = input("Paste the URL you are redirected to:")
            await self.authenticate_user(auth_response=url)
        else:
            self.callback_reached.wait(config.auth.callback.timeout)
            await self.stop_callback()

    @staticmethod
    async def stop_callback():
        try:
            async with aiohttp.request(
                "GET", f"http://localhost:{config.auth.callback.port}"
            ) as resp:
                await resp.read()
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass

    def start_callback(self):
        self.callback_reached.clear()

        async def callback(request):
            if self.callback_reached.is_set():
                raise GracefulExit

            code = request.query["code"]
            state = request.query.get("code")
            html = AUTH_HTML_FILE.read_text()  # pylint: disable=no-member
            try:
                asyncio.run_coroutine_threadsafe(
                    self.authenticate_user(code=code, state=state),
                    loop=self.callback_loop,
                ).result(config.auth.callback.timeout)
                html = html.replace("SPOTIFY_AUTH_MESSAGE", "Successfully logged in!")
                html = html.replace("BACKGROUND_COLOR", "#65D46E")
            except Exception as exc:
                logger.exception(exc)
                html = html.replace(
                    "SPOTIFY_AUTH_MESSAGE", "Could not get authorization token."
                )
                html = html.replace("BACKGROUND_COLOR", "#EC2E50")
            finally:
                self.callback_reached.set()
            return aiohttp.web.Response(body=html, content_type="text/html")

        web_app.router.add_get("/", callback)
        threading.Thread(
            target=run_app, daemon=True, args=(self.callback_loop,)
        ).start()
