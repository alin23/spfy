import inspect

import hug
from gunicorn.app.base import BaseApplication


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

    def runserver(self, **gunicorn_options):
        for name, method in inspect.getmembers(self, inspect.ismethod):
            hug.get(f'/{name}')(method)

        from ..client import __hug__ as client_hug
        __hug__.extend(client_hug)  # noqa

        app = StandaloneApplication(__hug_wsgi__, **gunicorn_options)  # noqa
        app.run()
