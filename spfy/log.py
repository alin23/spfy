import os
import logging
import pathlib

import daiquiri


def get_logger(level=logging.INFO):
    logdir = pathlib.Path.home().joinpath('.logs')
    if not logdir.exists():
        logdir.mkdir(parents=True)

    daiquiri.setup(outputs=(
        daiquiri.output.STDERR,
        daiquiri.output.File(directory=logdir)
    ), level=level)

    logger = daiquiri.getLogger()

    if os.getenv('FIRE_DEBUG'):
        logger.setLevel(logging.DEBUG)

    return logger
