"""
Scoring Function For Sonic Vault.

Takes The Measurement Data Returned By CsvScrapper.scrap() And Returns It With 12 Scores Added To Every IEM,
On A 1-10 Scale :
    9 Detailed Bands  : Sub Bass, Mid Bass, Upper Bass, Lower Mids, Center Mids,
                        Upper Mids, Lower Treble, Mid Treble, Upper Treble
    3 Simple Bands    : Bass, Mids, Treble (One Value For The Whole Region)

Usage:
    import score
    scored = score.score_data(data["dataSet"])
    for name, measurements, scores in scored:
        if scores is None:          # Duplicate Name Or Invalid Measurements, Not Scored
            continue
        ...                         # scores Is A 12-Tuple, Order = score.SCORE_COLUMNS

How Each IEM Is Scored:
    1. Smooth The Curve (1/6 Octave) And Subtract The Harman IE 2019 Target.
    2. Re-Center On The Median Of 250-1200 Hz.
    3. Reduce Each Of The 12 Bands To One dB Value.
    4. Map That dB Value To A Score Using Percentile Anchors Of The Whole Group
       (10th Percentile = 1, Median = 5.5, 90th Percentile = 10, Unclipped).
"""

from __future__ import annotations

import logging

import numpy as np

from constants import FREQUENCY, HARMAN_2019_RAW

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# --------------------------------------------------------------------------- #
# Configuration (Everything You Might Want To Tune Lives Here)
# --------------------------------------------------------------------------- #


BAND_COLUMNS = (
    "sub_bass", "mid_bass", "upper_bass",
    "lower_mids", "center_mids", "upper_mids",
    "lower_treble", "mid_treble", "upper_treble",
)

# Band Edges In Hz. Band k Covers [EDGES[k], EDGES[k + 1]) (Half-Open, So No Point Is Counted Twice).
# Points Above The Last Edge (16 kHz+) Are Ignored, That Region Mostly Measures The Coupler.
BAND_EDGES_HZ = (20, 60, 150, 250, 600, 1200, 2500, 6000, 10000, 16000)

# How Each Detailed Band Is Reduced To One Value : "mean" Or "median".
AGGREGATORS = ("mean",) * 8 + ("median",)

# Which Detailed Bands Each Simple Band Covers (Zero-Based Positions, Must Be Consecutive).
# A Simple Band Spans The Whole Frequency Range Of Its Bands.
MACRO_GROUPS = {"bass": (0, 1, 2), "mids": (3, 4, 5), "treble": (6, 7, 8)}

RECENTER_RANGE_HZ = (250, 1200)   # Median Of This Range Becomes 0 dB
SMOOTH_POINTS = 11                # ~1/6 Octave On The 1% Grid, Must Be Odd

SCORE_MIN, SCORE_MID, SCORE_MAX = 1.0, 5.5, 10.0   # Score Of The 10th Pct, Median And 90th Pct
STORED_SCORE_RANGE = (-2.0, 13.0)                  # Outlier Cap, Scores Beyond 1-10 Are Kept On Purpose
MIN_SPAN_DB = 0.5                                  # Guards Against Division By ~0 For Very Flat Bands
MIN_GROUP_SIZE = 10                                # Percentiles Of Fewer IEMs Are Not Meaningful


# --------------------------------------------------------------------------- #
# Precomputed Constants
# --------------------------------------------------------------------------- #

_FREQ = np.asarray(FREQUENCY, dtype=float)
_HARMAN = np.asarray(HARMAN_2019_RAW, dtype=float)

if _FREQ.shape != _HARMAN.shape:
    raise ValueError("FREQUENCY And HARMAN_2019_RAW Must Have The Same Length.")

N_BANDS = len(BAND_COLUMNS)                    # 9 Detailed Bands
MACRO_NAMES = tuple(MACRO_GROUPS)              # ("bass", "mids", "treble")
SCORE_COLUMNS = BAND_COLUMNS + MACRO_NAMES     # Order Of The 12 Values In Every Scores Tuple
N_SCORES = len(SCORE_COLUMNS)                  # 12

if not (len(AGGREGATORS) == N_BANDS == len(BAND_EDGES_HZ) - 1):
    raise ValueError("BAND_COLUMNS, AGGREGATORS And BAND_EDGES_HZ Do Not Match.")

_BAND_MASKS = np.array([(_FREQ >= lo) & (_FREQ < hi) for lo, hi in zip(BAND_EDGES_HZ[:-1], BAND_EDGES_HZ[1:])])
if not _BAND_MASKS.sum(axis=1).all():
    raise ValueError("A Band Contains No Frequency Points.")


def _macro_mask(positions):
    """Frequency Points Covered By A Group Of Consecutive Detailed Bands."""
    first, last = min(positions), max(positions)
    if tuple(positions) != tuple(range(first, last + 1)):
        raise ValueError("The Bands Of A MACRO_GROUPS Entry Must Be Consecutive.")
    return (_FREQ >= BAND_EDGES_HZ[first]) & (_FREQ < BAND_EDGES_HZ[last + 1])


_SCORE_MASKS = np.vstack([_BAND_MASKS, [_macro_mask(MACRO_GROUPS[name]) for name in MACRO_NAMES]])   # (12, 695)
_SCORE_AGGREGATORS = AGGREGATORS + ("mean",) * len(MACRO_NAMES)
_RECENTER_MASK = (_FREQ >= RECENTER_RANGE_HZ[0]) & (_FREQ <= RECENTER_RANGE_HZ[1])


# --------------------------------------------------------------------------- #
# Curves -> Band Values (dB)
# --------------------------------------------------------------------------- #

def smooth_curves(curves, window=SMOOTH_POINTS):
    """
    Moving Average Along The Frequency Axis (Edges Are Padded With The Edge Value).
    :param curves: One Curve (695,) Or Many (n, 695)
    :return: Array Of Shape (n, 695)
    """
    arr = np.atleast_2d(np.asarray(curves, dtype=float))
    if window < 2:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    pad = window // 2
    padded = np.pad(arr, ((0, 0), (pad, pad)), mode="edge")
    csum = np.concatenate([np.zeros((arr.shape[0], 1)), np.cumsum(padded, axis=1)], axis=1)
    return (csum[:, window:] - csum[:, :-window]) / window


def prepare_curves(curves):
    """
    Raw dB Curves -> Smoothed Delta From Harman, Re-Centered On The Median Of 250-1200 Hz.
    :param curves: One Curve (695,) Or Many (n, 695) Measured On The Standard Frequency Grid
    :return: Array Of Shape (n, 695), Values Are dB Above/Below Neutral
    """
    arr = np.atleast_2d(np.asarray(curves, dtype=float))
    if arr.shape[1] != _FREQ.size:
        raise ValueError(f"Expected {_FREQ.size} Points Per Curve, Got {arr.shape[1]}")
    delta = smooth_curves(arr - _HARMAN)
    offset = np.median(delta[:, _RECENTER_MASK], axis=1, keepdims=True)
    return delta - offset


def band_values(prepared):
    """
    Reduces Prepared Curves To One dB Value Per Score (9 Detailed Bands, Then Bass, Mids, Treble).
    :param prepared: Output Of prepare_curves, Shape (n, 695)
    :return: Array Of Shape (n, 12)
    """
    prepared = np.atleast_2d(prepared)
    values = np.empty((prepared.shape[0], N_SCORES))
    for k, how in enumerate(_SCORE_AGGREGATORS):
        segment = prepared[:, _SCORE_MASKS[k]]
        values[:, k] = np.median(segment, axis=1) if how == "median" else segment.mean(axis=1)
    return values


# --------------------------------------------------------------------------- #
# dB -> Score
# --------------------------------------------------------------------------- #

def compute_anchors(values):
    """
    Percentile Anchors Of Every Score Across The Group Of IEMs Being Scored.
    :param values: Band Values In dB, Shape (n, 12)
    :return: Array (12, 3) With The 10th Percentile, Median And 90th Percentile Of Each Column
    :raises ValueError: If The Group Has Fewer Than MIN_GROUP_SIZE IEMs
    """
    values = np.asarray(values, dtype=float)
    if values.shape[0] < MIN_GROUP_SIZE:
        raise ValueError(f"Need At Least {MIN_GROUP_SIZE} IEMs To Compute Scores, Got {values.shape[0]}")
    q10, med, q90 = np.percentile(values, [10, 50, 90], axis=0)
    return np.stack([q10, med, q90], axis=1)


def band_to_score(values, anchors):
    """
    Piecewise-Linear Score : 10th Percentile -> 1, Median -> 5.5, 90th Percentile -> 10.
    The Lines Continue Past The Anchors (Extreme IEMs Stay Separable), Capped At STORED_SCORE_RANGE.
    :param values: dB Values, Shape (n, 12) Or (12,)
    :param anchors: Output Of compute_anchors
    """
    values = np.asarray(values, dtype=float)
    anchors = np.asarray(anchors, dtype=float)
    q10, med, q90 = anchors[:, 0], anchors[:, 1], anchors[:, 2]
    low_span = np.maximum(med - q10, MIN_SPAN_DB)
    high_span = np.maximum(q90 - med, MIN_SPAN_DB)
    offset = values - med
    scores = np.where(
        offset < 0,
        SCORE_MID + (SCORE_MID - SCORE_MIN) * offset / low_span,
        SCORE_MID + (SCORE_MAX - SCORE_MID) * offset / high_span,
    )
    return np.clip(scores, *STORED_SCORE_RANGE)


# --------------------------------------------------------------------------- #
# The Function To Call
# --------------------------------------------------------------------------- #

def score_data(data_set, return_anchors=False):
    """
    Scores Every IEM In The Data Returned By CsvScrapper.scrap().
    The Whole Input Is The Group, So The Percentiles Are Computed Across All Of It.
    Duplicate Names (Case-Insensitive, Like The 'main' Table) Only Count Once, The First One Wins,
    And Entries With Missing Or Invalid Measurement Values Are Skipped.

    :param data_set: data["dataSet"] : List Of (name, measurements), 695 Values Per IEM
    :param return_anchors: Also Return The Percentile Anchors, For Reference Or Storing
    :return: List In The Same Order As data_set, With A 12-Tuple Of Scores Added To Every Entry :
                 [(name, measurements, scores), ...]
             scores Is A Tuple Of 12 Floats In The Order Of score.SCORE_COLUMNS
             (9 Detailed Bands, Then Bass, Mids, Treble), Or None For A Skipped Entry.
             With return_anchors=True The Result Is (that_list, anchors) Where anchors Is A List Of
             12 Rows (band_number, q10, median, q90) In The Same Column Order.
    :raises ValueError: If Fewer Than MIN_GROUP_SIZE IEMs Can Be Scored
    """
    seen, usable, curves = set(), [], []
    for i, (name, measurements) in enumerate(data_set):
        key = name.lower()
        if key in seen:
            continue
        arr = np.asarray(measurements, dtype=float)
        if arr.shape != (_FREQ.size,) or not np.isfinite(arr).all():
            logger.warning(f"Not Scoring '{name}' : Missing Or Invalid Measurement Values")
            continue
        seen.add(key)
        usable.append(i)
        curves.append(arr)

    if len(usable) < MIN_GROUP_SIZE:
        raise ValueError(f"Only {len(usable)} IEMs Can Be Scored, Need At Least {MIN_GROUP_SIZE}")

    values = band_values(prepare_curves(np.array(curves)))
    anchors = compute_anchors(values)
    scores = band_to_score(values, anchors)

    scored = [(name, measurements, None) for name, measurements in data_set]
    for i, row in zip(usable, scores):
        name, measurements = data_set[i]
        scored[i] = (name, measurements, tuple(float(x) for x in row))
    logger.info(f"Scored {len(usable)} Of {len(data_set)} IEMs.")

    if return_anchors:
        return scored, [(k + 1, *map(float, row)) for k, row in enumerate(anchors)]
    return scored
