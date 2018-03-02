from typing import Dict, List

import pandas as pd

from .constants import MAX_KEY, MAX_LOUDNESS, MAX_POPULARITY, AudioFeature


def normalize_features(features: Dict[str, int], feature_values: List[Dict[str, float]]) -> pd.Series:
    """Normalizes a set of audio features to
       a list of sums of values between 0 and 1

    Args:
        features (dict): {feature: direction} where direction
                         should be 1 for ASC and -1 for DESC
        feature_values (list): list of dicts with feature values

    Returns:
        pd.Series: List of sums of feature values
    """
    feature_keys = features.keys()

    ids = [f.pop('id') for f in feature_values]
    idx = pd.Index(ids)
    data = pd.DataFrame(feature_values, dtype='float64', index=idx)

    if AudioFeature.TEMPO.value in feature_keys:
        data.tempo /= data.tempo.max()

    if AudioFeature.DURATION_MS.value in feature_keys:
        data.duration_ms /= data.duration_ms.max()

    if AudioFeature.TIME_SIGNATURE.value in feature_keys:
        data.time_signature /= data.time_signature.max()

    if AudioFeature.KEY.value in feature_keys:
        data.key /= MAX_KEY

    if AudioFeature.LOUDNESS.value in feature_keys:
        data.loudness = 1 - data.loudness / MAX_LOUDNESS

    if AudioFeature.POPULARITY.value in feature_keys:
        data.popularity /= MAX_POPULARITY

    for feature, direction in features.items():
        data[feature] *= direction

    return data.sum(axis=1)
