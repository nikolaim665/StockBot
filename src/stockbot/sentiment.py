"""Headline sentiment using VADER (offline, fast) with a few finance-specific words added."""

from __future__ import annotations

from functools import lru_cache

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

FINANCE_LEXICON = {
    "beat": 2.0, "beats": 2.0, "surge": 2.5, "surges": 2.5, "soar": 2.5, "soars": 2.5,
    "rally": 2.0, "rallies": 2.0, "upgrade": 2.0, "upgraded": 2.0, "outperform": 2.0,
    "record": 1.5, "bullish": 2.5, "buyback": 1.5, "jump": 1.5, "jumps": 1.5, "gains": 1.5,
    "miss": -2.0, "misses": -2.0, "plunge": -2.5, "plunges": -2.5, "tumble": -2.5,
    "tumbles": -2.5, "slump": -2.0, "slumps": -2.0, "downgrade": -2.0, "downgraded": -2.0,
    "underperform": -2.0, "bearish": -2.5, "lawsuit": -1.5, "probe": -1.5, "recall": -1.5,
    "layoffs": -1.5, "selloff": -2.0, "sell-off": -2.0, "falls": -1.5, "drops": -1.5,
    "warning": -1.5, "cuts": -1.0,
}

BULLISH, BEARISH = 0.15, -0.15


@lru_cache(maxsize=1)
def _analyzer() -> SentimentIntensityAnalyzer:
    a = SentimentIntensityAnalyzer()
    a.lexicon.update(FINANCE_LEXICON)
    return a


def score(text: str) -> float:
    return _analyzer().polarity_scores(text)["compound"]


def label(value: float | None) -> str:
    if value is None:
        return "–"
    if value >= BULLISH:
        return "Bullish"
    if value <= BEARISH:
        return "Bearish"
    return "Neutral"
