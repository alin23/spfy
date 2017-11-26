import inspect

import hug

try:
    from gunicorn.app.base import BaseApplication
except:
    pass


class StandaloneApplication(BaseApplication):
    def __init__(self, app, **options):
        self.options = options
        self.application = app
        super().__init__()

    def load_config(self):
        config = {
            k: v for k, v in self.options.items()
            if k in self.cfg.settings and v is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


class ServerMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.public_methods = [
            self.authenticate,
            self.current_user
        ]
        self.local_methods = [method for name, method in inspect.getmembers(self, inspect.ismethod)]

    def runserver(self, public=False, **gunicorn_options):
        methods = self.public_methods if public else self.local_methods
        for method in methods:
            hug.get(f'/{method.__name__}')(method)

        from ..client import __hug__ as client_hug
        from .auth import __hug__ as auth_hug
        from .email import __hug__ as email_hug
        from .player import __hug__ as player_hug
        from .recommender import __hug__ as recommender_hug
        __hug__.extend(client_hug)  # noqa
        __hug__.extend(auth_hug)  # noqa
        __hug__.extend(email_hug)  # noqa
        __hug__.extend(player_hug)  # noqa
        __hug__.extend(recommender_hug)  # noqa

        app = StandaloneApplication(__hug_wsgi__, **gunicorn_options)  # noqa
        app.run()
