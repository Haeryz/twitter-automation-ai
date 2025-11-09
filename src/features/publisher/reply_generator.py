"""Context-aware reply generation with guardrails to keep responses on-topic."""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from core.llm_service import LLMService
from data_models import LLMSettings, ScrapedTweet
from utils.text_utils import (
    describe_media_urls,
    extract_keywords_from_texts,
    infer_tone_from_samples,
    is_probably_humorous,
    tokenize_for_overlap,
)

logger = logging.getLogger(__name__)

MAX_REPLY_CHARS = 270
DEFAULT_OFF_TOPIC_TERMS: Tuple[str, ...] = (
    "claude",
    "anthropic",
    "openai",
    "chatgpt",
    "opencv",
    "repo",
    "pull request",
    "merge request",
    "commit",
    "stack trace",
    "stacktrace",
    "exception",
    "bugfix",
    "script",
    "terminal",
    "command line",
)

MEDIA_DOWNLOAD_TIMEOUT = 12.0
MAX_INLINE_MEDIA_SIZE = 6 * 1024 * 1024  # 6 MiB safety budget


def _normalize_urls(urls: Optional[Sequence[str]]) -> List[str]:
    if not urls:
        return []
    return [str(url) for url in urls if url]


def _prepare_tweet_context(tweet: ScrapedTweet) -> Dict[str, Any]:
    text = (tweet.text_content or "").strip()
    keywords = extract_keywords_from_texts([text], max_keywords=6)
    tone = infer_tone_from_samples([text])
    media_urls = _normalize_urls(getattr(tweet, "embedded_media_urls", None))
    media_note = describe_media_urls(media_urls)
    humor_flag = is_probably_humorous(text)

    descriptor_segments: List[str] = [f"Tone: {tone}."]
    if humor_flag:
        descriptor_segments.append("Humorous or meme-like language detected.")
    if text.count("?"):
        descriptor_segments.append("This tweet asks a question; answer it directly.")
    if not text and media_urls:
        descriptor_segments.append("Tweet has no textual caption; rely on media context or acknowledge if you cannot view it.")
    descriptor = " ".join(descriptor_segments)

    return {
        "text": text,
        "keywords": keywords,
        "media_urls": media_urls,
        "media_note": media_note,
        "descriptor": descriptor,
        "humor_flag": humor_flag,
    }


def should_apply_style_profile(tweet: ScrapedTweet, style_keywords: Sequence[str]) -> bool:
    """Return True if the account style should influence the reply."""
    if not style_keywords:
        return False
    context = _prepare_tweet_context(tweet)
    if context["humor_flag"]:
        return False
    tweet_tokens = tokenize_for_overlap(context["text"])
    overlap = tweet_tokens.intersection({keyword.lower() for keyword in style_keywords})
    return bool(overlap)


def _find_off_topic_terms(
    reply_text: str,
    tweet_text: str,
    allowed_terms: Sequence[str],
) -> List[str]:
    reply_lower = reply_text.lower()
    allowed = {term.lower() for term in allowed_terms}
    allowed.update(tokenize_for_overlap(tweet_text))
    return [
        term
        for term in DEFAULT_OFF_TOPIC_TERMS
        if term in reply_lower and term not in allowed
    ]


def _build_instruction(
    tweet: ScrapedTweet,
    tweet_context: Dict[str, Any],
    *,
    style_summary: Optional[str],
    persona_handle: Optional[str],
    banned_terms: Sequence[str],
    feedback: Optional[str],
) -> str:
    focus_keywords = tweet_context.get("keywords") or []
    media_note = tweet_context.get("media_note", "No media attached.")
    descriptor = tweet_context.get("descriptor", "")
    handle = tweet.user_handle or "user"

    lines = [
        "You are crafting a public reply on X (Twitter).",
        "Your reply must stay tightly focused on the tweet's content.",
        f"Allowed length: <= {MAX_REPLY_CHARS} characters.",
        "Do not fabricate knowledge about attached media; if unsure, acknowledge uncertainty briefly.",
        "If you cannot determine what is in the media, explicitly note that instead of guessing.",
    ]
    if style_summary:
        lines.append("Match the following style cues when relevant:")
        lines.append(style_summary)
    else:
        lines.append("Use a neutral, conversational tone.")

    if feedback:
        lines.append(f"Correction guidance: {feedback}")

    keyword_line = (
        f"Prioritise these tweet keywords in your reply: {', '.join(focus_keywords)}."
        if focus_keywords
        else "Focus on what the tweet explicitly states."
    )
    banned_line = (
        f"Avoid these off-topic terms unless the tweet mentions them: {', '.join(banned_terms)}."
        if banned_terms
        else ""
    )

    if not tweet_context.get("text"):
        lines.append("The tweet has no visible text caption; rely solely on the media or acknowledge that you cannot see it.")

    instruction = (
        "\n".join(lines)
        + "\n\n" + keyword_line
        + ("\n" + banned_line if banned_line else "")
        + "\n\nTweet details:\n"
        f"- Author handle: @{handle}\n"
        f"- Tweet text: {tweet_context['text'] or '[no text supplied]'}\n"
        f"- Media note: {media_note}\n"
        f"- Descriptor: {descriptor or 'Neutral'}\n"
    )
    if persona_handle:
        instruction += f"- You are replying as @{persona_handle}.\n"

    instruction += (
        "\nRespond with JSON having this schema: {\n"
        "  \"reply_text\": string,\n"
        "  \"is_relevant\": boolean,\n"
        "  \"relevance_reason\": string,\n"
        "  \"referenced_topics\": array of strings (0-4 items)\n"
        "}."
    )
    instruction += (
        "\nMark is_relevant=false if your reply fails to reference the tweet's subject."
        " Provide concise rationale in relevance_reason."
    )

    return instruction


def _merge_unique(sequence: Sequence[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in sequence:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(item)
    return ordered


async def _download_media_to_data_url(url: str) -> Optional[str]:
    def _fetch() -> Optional[str]:
        response = requests.get(url, timeout=MEDIA_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        content = response.content
        if len(content) > MAX_INLINE_MEDIA_SIZE:
            raise ValueError(f"media payload exceeds {MAX_INLINE_MEDIA_SIZE} bytes")
        mime = response.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        encoded = base64.b64encode(content).decode('ascii')
        return f"data:{mime};base64,{encoded}"

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        logger.warning("Failed to inline media %s for Gemini: %s", url, exc)
        return None


async def _prepare_inline_media_for_service(
    inline_media: List[Dict[str, Any]],
    service_preference: Optional[str],
) -> List[Dict[str, Any]]:
    if not inline_media or not service_preference or 'gemini' not in service_preference.lower():
        return inline_media

    prepared: List[Dict[str, Any]] = []
    for entry in inline_media:
        new_entry = dict(entry)
        parts = []
        for part in entry.get('parts', []) if isinstance(entry, dict) else []:
            if not isinstance(part, dict) or part.get('type') != 'media':
                parts.append(part)
                continue

            source = part.get('source') if isinstance(part, dict) else {}
            if not isinstance(source, dict):
                parts.append(part)
                continue

            src_type = source.get('type', 'url').lower()
            if src_type == 'data_url':
                parts.append(part)
                continue

            url = source.get('url')
            if not url:
                parts.append(part)
                continue

            data_url = await _download_media_to_data_url(str(url))
            if not data_url:
                parts.append(part)
                continue

            new_part = dict(part)
            new_source = dict(source)
            new_source['type'] = 'data_url'
            new_source['data_url'] = data_url
            new_source.pop('url', None)
            new_part['source'] = new_source
            parts.append(new_part)

        new_entry['parts'] = parts
        prepared.append(new_entry)

    return prepared


async def generate_guarded_reply(
    llm_service: LLMService,
    tweet: ScrapedTweet,
    llm_settings: LLMSettings,
    *,
    system_prompt: Optional[str],
    style_summary: Optional[str],
    persona_handle: Optional[str],
    inline_media: Optional[List[Dict[str, Any]]] = None,
    banned_terms: Optional[Sequence[str]] = None,
    retry_limit: int = 2,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Generate a reply that passes basic topical guardrails."""

    tweet_context = _prepare_tweet_context(tweet)
    focus_keywords = tweet_context.get("keywords") or []
    banned_terms = _merge_unique(list(DEFAULT_OFF_TOPIC_TERMS) + list(banned_terms or []))

    prepared_inline_media = await _prepare_inline_media_for_service(
        list(inline_media or []),
        llm_settings.service_preference,
    )

    logger.info(
        "Reply generation request for tweet %s: style_applied=%s, media_count=%s, text_chars=%s",
        getattr(tweet, "tweet_id", "unknown"),
        bool(style_summary),
        len(tweet_context.get("media_urls", [])),
        len(tweet_context.get("text", "")),
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": "Final reply under 270 characters.",
            },
            "is_relevant": {"type": "boolean"},
            "relevance_reason": {
                "type": "string",
                "description": "Brief reason explaining relevance judgement.",
            },
            "referenced_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key topics mentioned in the reply.",
            },
        },
        "required": ["reply_text", "is_relevant", "relevance_reason"],
    }

    attempt = 0
    last_error: Optional[str] = None

    max_attempts = max(1, retry_limit)
    while attempt < max_attempts:
        feedback = last_error if attempt > 0 else None
        instruction = _build_instruction(
            tweet,
            tweet_context,
            style_summary=style_summary,
            persona_handle=persona_handle,
            banned_terms=banned_terms,
            feedback=feedback,
        )

        logger.debug(
            "LLM attempt %s instruction preview: %s",
            attempt + 1,
            instruction[:600].replace("\n", " | "),
        )
        if prepared_inline_media:
            media_urls = []
            for media in prepared_inline_media:
                parts = media.get('parts', []) if isinstance(media, dict) else []
                for part in parts:
                    if isinstance(part, dict) and part.get('type') == 'media':
                        source = part.get('source') or {}
                        if source.get('type') == 'data_url':
                            media_urls.append('<embedded-data-url>')
                        else:
                            url = source.get('url')
                            if url:
                                media_urls.append(str(url))
            logger.debug("Inline media URLs for attempt %s: %s", attempt + 1, media_urls or "(none)")

        data, err = await llm_service.generate_structured(
            task_instruction=instruction,
            schema=schema,
            service_preference=llm_settings.service_preference,
            system_prompt=system_prompt,
            model_name=llm_settings.model_name_override,
            max_tokens=llm_settings.max_tokens,
            temperature=llm_settings.temperature,
            hard_character_limit=MAX_REPLY_CHARS,
            inline_media=prepared_inline_media,
        )

        if not data or not isinstance(data, dict):
            last_error = err or "No structured response produced."
            logger.debug("Structured reply attempt failed: %s", last_error)
            attempt += 1
            continue

        reply_text = (data.get("reply_text") or "").strip()
        if reply_text:
            reply_text = reply_text[:MAX_REPLY_CHARS].rstrip()
        is_relevant = bool(data.get("is_relevant"))
        relevance_reason = (data.get("relevance_reason") or "").strip()
        referenced_topics = data.get("referenced_topics") or []

        flagged_terms = _find_off_topic_terms(
            reply_text,
            tweet_context["text"],
            allowed_terms=focus_keywords,
        ) if reply_text else []

        too_long = bool(reply_text and len(reply_text) > MAX_REPLY_CHARS)
        missing_reply = not reply_text

        if missing_reply:
            last_error = "No reply text returned."
        elif too_long:
            last_error = "Reply exceeded character limit."
        elif not is_relevant:
            last_error = relevance_reason or "Model flagged reply as not relevant."
        elif flagged_terms:
            last_error = f"Reply referenced off-topic terms: {', '.join(flagged_terms)}."
        else:
            logger.info(
                "LLM reply accepted for tweet %s on attempt %s: %s (reason: %s)",
                getattr(tweet, "tweet_id", "unknown"),
                attempt + 1,
                reply_text,
                relevance_reason or "(no reason provided)",
            )
            metadata = {
                "relevance_reason": relevance_reason,
                "referenced_topics": referenced_topics,
                "attempts": attempt + 1,
                "flagged_terms": [],
            }
            return reply_text, metadata

        logger.debug("Reply guard rejected attempt %s: %s", attempt + 1, last_error)
        attempt += 1

    logger.warning(
        "LLM reply generation failed for tweet %s after %s attempts: %s",
        getattr(tweet, "tweet_id", "unknown"),
        attempt,
        last_error,
    )
    failure_metadata = {
        "relevance_reason": last_error or "Unknown guard failure.",
        "referenced_topics": [],
        "attempts": attempt,
        "flagged_terms": [],
    }
    return None, failure_metadata


__all__ = [
    "generate_guarded_reply",
    "should_apply_style_profile",
]
