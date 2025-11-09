"""Helpers for constructing concise per-account style snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Sequence, Tuple, Dict, Any, Set

from data_models import ScrapedTweet
from utils.text_utils import (
    extract_keywords_from_texts,
    infer_tone_from_samples,
    estimate_media_usage_ratio,
)


def _normalize_handle(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lstrip("@")
    if not text:
        return None
    text = text.split("?")[0].strip("/")
    if text.lower().startswith("https://"):
        parts = text.split("x.com/")
        if len(parts) > 1:
            text = parts[-1]
    return text.lower() or None


def filter_to_self_posts(
    tweets: Sequence[ScrapedTweet],
    candidate_handles: Iterable[str],
    *,
    minimum: int = 3,
) -> List[ScrapedTweet]:
    allowed: Set[str] = {
        handle
        for handle in (_normalize_handle(h) for h in candidate_handles)
        if handle
    }
    if not allowed:
        return list(tweets)

    filtered = [
        tweet
        for tweet in tweets
        if _normalize_handle(tweet.user_handle) in allowed
    ]
    if len(filtered) >= minimum:
        return filtered
    # Not enough self-authored posts; fall back to mixed list rather than returning empty.
    return list(tweets)


def build_style_snapshot(
    tweets: Sequence[ScrapedTweet],
    candidate_handles: Sequence[str],
    *,
    max_items: int = 5,
) -> Tuple[str, Dict[str, Any]]:
    """Return (style_context_text, style_memory_dict)."""
    if not tweets:
        return "", {}

    relevant_tweets = filter_to_self_posts(tweets, candidate_handles)

    seen_ids: Set[str] = set()
    deduped: List[ScrapedTweet] = []
    for tweet in relevant_tweets:
        tweet_id = getattr(tweet, "tweet_id", None)
        if not tweet_id or tweet_id in seen_ids:
            continue
        seen_ids.add(tweet_id)
        deduped.append(tweet)

    if not deduped:
        return "", {}

    epoch_guard = datetime.min.replace(tzinfo=timezone.utc)
    deduped.sort(key=lambda t: getattr(t, "created_at", None) or epoch_guard, reverse=True)
    selected = deduped[:max_items]

    context_lines: List[str] = []
    memory_entries: List[Dict[str, Any]] = []
    media_entries = 0

    for idx, tweet in enumerate(selected, start=1):
        text_raw = getattr(tweet, "text_content", "") or ""
        snippet = " ".join(text_raw.split())[:220]
        created_at = getattr(tweet, "created_at", None)
        if created_at:
            try:
                created_at_utc = created_at.astimezone(timezone.utc)
            except Exception:
                created_at_utc = created_at
            timestamp_label = created_at_utc.strftime("%Y-%m-%d %H:%M UTC")
            timestamp_iso = created_at_utc.isoformat()
        else:
            timestamp_label = "Unknown time"
            timestamp_iso = None

        media_urls = [
            str(url)
            for url in (getattr(tweet, "embedded_media_urls", []) or [])
            if url
        ]
        has_media = bool(media_urls)
        if has_media:
            media_entries += 1

        context_lines.append(
            f"{idx}. {timestamp_label} | {snippet}"
        )
        memory_entries.append(
            {
                "tweet_id": getattr(tweet, "tweet_id", None),
                "url": str(getattr(tweet, "tweet_url", "")) or None,
                "created_at": timestamp_iso,
                "likes": getattr(tweet, "like_count", 0) or 0,
                "retweets": getattr(tweet, "retweet_count", 0) or 0,
                "replies": getattr(tweet, "reply_count", 0) or 0,
                "views": getattr(tweet, "view_count", 0) or 0,
                "text": snippet,
                "media_urls": media_urls,
            }
        )

    style_context_text = "Recent personal posting snapshot:\n" + "\n".join(context_lines)
    if len(style_context_text) > 800:
        style_context_text = style_context_text[:800].rstrip() + "…"

    texts = [entry["text"] for entry in memory_entries if entry.get("text")]
    keywords = extract_keywords_from_texts(texts, max_keywords=8)
    tone = infer_tone_from_samples(texts)
    media_ratio = estimate_media_usage_ratio(media_entries, len(memory_entries))

    summary_lines = []
    if keywords:
        summary_lines.append(f"Topics: {', '.join(keywords[:4])}.")
    if tone:
        summary_lines.append(f"Tone: {tone}.")
    summary_lines.append(f"Media usage: {int(media_ratio * 100)}% of recent posts include media.")
    style_summary = "\n".join(f"• {line}" for line in summary_lines)

    style_memory = {
        "primary_handle": next((h for h in candidate_handles if h), None),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": memory_entries,
        "media_entry_count": media_entries,
        "style_summary": style_summary,
        "keyword_signature": keywords,
    }

    return style_context_text, style_memory


__all__ = [
    "build_style_snapshot",
    "filter_to_self_posts",
]
