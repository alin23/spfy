from mailer import Mailer, Message

from .. import config, logger, root

LOGIN_HTML = root / "html" / "login.html"


# pylint: disable=too-few-public-methods


class EmailMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def send_auth_email(email, auth_url):
        logger.info("Login here to use Spotify API: %s", auth_url)
        mailer = Mailer(**config.email)
        # pylint: disable=no-member
        html_content = LOGIN_HTML.read_text().replace(
            "SPOTIFY_AUTHENTICATION_URL", auth_url
        )
        message = Message(From=config.email.usr or email, To=email, charset="utf-8")
        message.Subject = "Spotify API Authentication"
        message.Html = html_content
        message.Body = f"Login here to use Spotify API: {auth_url}"
        mailer.send(message)
