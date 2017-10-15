from mailer import Mailer, Message

from .. import root, config, logger

LOGIN_HTML = root / 'html' / 'login.html'


class EmailMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def send_auth_email(self, email, auth_url):
        logger.info(f'Login here to use Spotify API: {auth_url}')

        mailer = Mailer(**config.email)
        html_content = LOGIN_HTML.read_text().replace('SPOTIFY_AUTHENTICATION_URL', auth_url)

        message = Message(
            From=config.email.usr or email,
            To=email,
            charset="utf-8")
        message.Subject = "Spotify API Authentication"
        message.Html = html_content
        message.Body = f'Login here to use Spotify API: {auth_url}'

        mailer.send(message)
