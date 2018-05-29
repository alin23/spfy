import inspect
from typing import Dict, List
from itertools import chain, repeat

import pandas as pd

from .constants import AudioFeature, AudioFeatureRange

MAX_KEY = AudioFeatureRange.KEY.value[-1]
MAX_LOUDNESS = AudioFeatureRange.LOUDNESS.value[0]
MAX_POPULARITY = AudioFeatureRange.POPULARITY.value[-1]


def normalize_features(
    features: List[Dict[str, float]], track_ids: List[str]
) -> pd.DataFrame:
    """Normalizes a set of audio features to values between 0 and 1

    Args:
        features (list): list of dicts with feature values
        track_ids (list): list of track ids to use as index

    Returns:
        pd.DataFrame: Feature values between 0 and 1
    """
    # pylint: disable=no-member
    data = pd.DataFrame(features, dtype="float64", index=pd.Index(track_ids))
    if AudioFeature.TEMPO.value in data:
        data.tempo /= data.tempo.max()
    if AudioFeature.DURATION_MS.value in data:
        data.duration_ms /= data.duration_ms.max()
    if AudioFeature.TIME_SIGNATURE.value in data:
        data.time_signature /= data.time_signature.max()
    if AudioFeature.KEY.value in data:
        data.key /= MAX_KEY
    if AudioFeature.LOUDNESS.value in data:
        data.loudness = 1 - data.loudness / MAX_LOUDNESS
    if AudioFeature.POPULARITY.value in data:
        data.popularity /= MAX_POPULARITY
    return data


def ncycles(iterable, n):
    "Returns the sequence elements n times"
    return chain.from_iterable(repeat(tuple(iterable), n))


def function_trace():
    return " -> ".join(f.function for f in reversed(inspect.stack()[1:]))
