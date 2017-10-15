import socket
import threading

import hug
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
from wsgiref.simple_server import make_server

from .. import root, config, logger
from ..cache import User, get, db_session
from ..constants import API, AuthFlow, AllScopes
from ..exceptions import SpotifyCredentialsException

AUTH_HTML_FILE = root / 'html' / 'auth_message.html'


class AuthMixin:
    def __init__(self, client_id=None, client_secret=None, redirect_uri=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client_id = client_id or config.app.client_id
        self.client_secret = client_secret or config.app.client_secret
        self.redirect_uri = self._get_redirect_uri(redirect_uri)

        self.session = None
        self.userid = None

        self.callback_reached = threading.Event()

    def _get_redirect_uri(self, redirect_uri):
        redirect_uri = (
            redirect_uri or
            config.app.redirect_uri or
            f'http://{socket.gethostname()}.local')

        if config.auth.callback.enabled and config.auth.callback.port and redirect_uri:
            redirect_uri += f':{config.auth.callback.port}'

        return redirect_uri

    @property
    @db_session
    def user(self):
        return User[self.userid]

    @property
    def is_authenticated(self):
        return bool(self.session and self.session.token)

    @db_session
    def authenticate_user(self, userid=None, username=None, email=None, code=None, state=None, auth_response=None, scope=AllScopes):
        self.session = OAuth2Session(self.client_id, redirect_uri=self.redirect_uri, scope=scope, auto_refresh_url=API.TOKEN.value)
        self.request = self.session.request

        user = get(u for u in User if u.id == userid or u.username == username or u.email == email)
        if user:
            self.userid = user.id
            self.session.token = user.token
            self.session.token_updater = User.token_updater(user.id)
            return True

        if code:
            token = self.session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=code, state=state,
                authorization_response=auth_response)

            user_details = self.current_user()
            user = User(username=user_details.id, email=user_details.email, token=token)
            self.userid = user.id
            return True

        return False

    @db_session
    def authenticate_server(self):
        default_user = User.default()
        self.userid = default_user.id

        self.session = OAuth2Session(client=BackendApplicationClient(self.client_id))
        self.session.token_updater = User.token_updater(default_user.id)

        if default_user.token:
            self.session.token = default_user.token
        else:
            default_user.token = self.session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret)

        return True

    def authenticate(self, flow=config.auth.flow, **auth_params):
        if not (self.client_id and self.client_secret):
            raise SpotifyCredentialsException

        flow = AuthFlow(flow)
        if flow == AuthFlow.CLIENT_CREDENTIALS:
            self.authenticate_server()
        elif flow == AuthFlow.AUTHORIZATION_CODE:
            if not self.authenticate_user(**auth_params):
                if config.auth.callback.enabled:
                    self.start_callback()

                authorization_url, _ = self.session.authorization_url(API.AUTHORIZE.value)
                if config.auth.send_auth_url_to_email:
                    email = auth_params.get('email') or config.auth.email
                    self.send_auth_email(email, authorization_url)
                else:
                    print(f'Login here: {authorization_url}')

                self.wait_for_authorization()

    def wait_for_authorization(self):
        if not config.auth.callback.enabled:
            url = input('Paste the URL you are redirected to:')
            self.authenticate_user(auth_response=url)
        else:
            self.callback_reached.wait(config.auth.callback.timeout)
            self.stop_callback()

    def stop_callback(self):
        if self.httpd:
            self.httpd.shutdown()

    def start_callback(self):
        self.callback_reached.clear()

        @hug.get('/', output=hug.output_format.html)
        def callback(code: hug.types.text, state: hug.types.text):
            html = AUTH_HTML_FILE.read_text()
            try:
                self.authenticate_user(code=code, state=state)
                html = html.replace('SPOTIFY_AUTH_MESSAGE', 'Successfully logged in!')
                html = html.replace('BACKGROUND_COLOR', '#65D46E')
            except Exception as exc:
                logger.exception(exc)
                html = html.replace('SPOTIFY_AUTH_MESSAGE', 'Could not get authorization token.')
                html = html.replace('BACKGROUND_COLOR', '#EC2E50')
            finally:
                self.callback_reached.set()

            return html

        api = __hug__.http.server(None)  # noqa
        self.httpd = make_server('', config.auth.callback.port, api)

        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
