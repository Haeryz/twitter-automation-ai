"""Utility helpers for lightweight text analysis and keyword extraction.

These helpers intentionally avoid heavy NLP dependencies so they can run
in constrained environments (e.g. headless automation workers).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List, Sequence, Set

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")
# A compact stopword list to filter out non-informative tokens. We avoid pulling in
# external libraries to keep the runtime light. Only include lowercase entries.
_STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "it's",
    "just",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "ours",
    "she",
    "so",
    "than",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "too",
    "up",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "you",
    "your",
    "you're",
    "amp",
    "rt",
    "http",
    "https",
    "www",
}

_HUMOR_MARKERS = {"lol", "lmao", "haha", "haha", "hehe", "😂", "🤣", "🤣", "😹", "meme"}
_TECH_MARKERS = {
    "api",
    "code",
    "model",
    "deploy",
    "release",
    "ai",
    "ml",
    "data",
    "research",
    "update",
    "version",
    "script",
}
_SENTIMENT_MARKERS = {
    "amazing": 1,
    "awesome": 1,
    "love": 1,
    "hate": -1,
    "terrible": -1,
    "awful": -1,
    "great": 1,
    "good": 1,
    "bad": -1,
    "thrilled": 1,
    "furious": -1,
}


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]


def tokenize_for_overlap(text: str) -> Set[str]:
    """Return a set of normalized tokens suitable for overlap checks."""
    return {
        token
        for token in _tokenize(text)
        if token not in _STOPWORDS and len(token) > 2
    }


def extract_keywords_from_texts(
    texts: Iterable[str],
    *,
    max_keywords: int = 8,
    min_frequency: int = 1,
) -> List[str]:
    """Extract top keywords from the supplied texts using a simple frequency tally."""
    counter: Counter[str] = Counter()
    for text in texts:
        for token in _tokenize(text):
            if len(token) <= 2:
                continue
            if token in _STOPWORDS:
                continue
            counter[token] += 1
    if not counter:
        return []
    filtered = [token for token, count in counter.items() if count >= min_frequency]
    if not filtered:
        filtered = list(counter.keys())
    top_tokens = sorted(
        filtered,
        key=lambda t: (counter[t], -len(t), t),
        reverse=True,
    )
    return top_tokens[:max_keywords]


def infer_tone_from_samples(texts: Sequence[str]) -> str:
    """Infer a coarse tone from sample texts (playful, technical, or conversational)."""
    humor_score = 0
    tech_score = 0
    exclamation_score = 0
    sentiment_score = 0

    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        humor_score += sum(1 for marker in _HUMOR_MARKERS if marker in lowered)
        tech_score += sum(1 for marker in _TECH_MARKERS if marker in lowered)
        exclamation_score += lowered.count("!")
        for marker, weight in _SENTIMENT_MARKERS.items():
            sentiment_score += lowered.count(marker) * weight

    if humor_score >= max(1, tech_score // 2):
        return "playful"
    if tech_score > 0 and tech_score >= humor_score:
        return "technical"
    if exclamation_score > 2 or sentiment_score > 2:
        return "enthusiastic"
    if sentiment_score < -1:
        return "cautious"
    return "conversational"


def estimate_media_usage_ratio(entries_with_media: int, total_entries: int) -> float:
    if total_entries <= 0:
        return 0.0
    return round(entries_with_media / float(total_entries), 2)


def is_probably_humorous(text: str) -> bool:
    tokens = tokenize_for_overlap(text)
    if not tokens:
        return False
    humor_tokens = tokens.intersection({marker.strip("#") for marker in _HUMOR_MARKERS})
    return bool(humor_tokens)


def describe_media_urls(urls: Sequence[str]) -> str:
    if not urls:
        return "No media attached."
    image_types = 0
    video_types = 0
    gif_types = 0
    for url in urls:
        lowered = url.lower()
        if lowered.endswith((".gif",)):
            gif_types += 1
        elif lowered.endswith((".mp4", "m3u8")):
            video_types += 1
        else:
            image_types += 1
    segments = []
    if image_types:
        segments.append(f"{image_types} image(s)")
    if video_types:
        segments.append(f"{video_types} video(s)")
    if gif_types:
        segments.append(f"{gif_types} gif(s)")
    summary = ", ".join(segments) if segments else f"{len(urls)} media item(s)"
    return f"Media detected: {summary}."


def harmonic_mean(values: Sequence[float]) -> float:
    cleaned = [v for v in values if v > 0]
    if not cleaned:
        return 0.0
    return round(len(cleaned) / sum(1.0 / v for v in cleaned), 4)

__all__ = [
    "extract_keywords_from_texts",
    "tokenize_for_overlap",
    "infer_tone_from_samples",
    "estimate_media_usage_ratio",
    "is_probably_humorous",
    "describe_media_urls",
    "harmonic_mean",
]
