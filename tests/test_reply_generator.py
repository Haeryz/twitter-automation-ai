"""Tests for guarded reply generation guardrails."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project src/ directory is on sys.path for direct imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.append(str(SRC_PATH))

from data_models import LLMSettings, ScrapedTweet  # noqa: E402  pylint: disable=wrong-import-position
from features.publisher.reply_generator import (  # noqa: E402  pylint: disable=wrong-import-position
    generate_guarded_reply,
    should_apply_style_profile,
)
import features.publisher.reply_generator as reply_generator  # noqa: E402  pylint: disable=wrong-import-position


class StubLLMService:
    """Simple stub to emulate LLMService.generate_structured responses."""

    def __init__(self, responses):
        # Each response entry should be a tuple of (data_dict, error_str)
        self._responses = list(responses)
        self.calls = []

    async def generate_structured(self, **kwargs):  # pylint: disable=unused-argument
        self.calls.append(kwargs)
        if not self._responses:
            return None, "no-response"
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_generate_guarded_reply_success_on_first_attempt():
    tweet = ScrapedTweet(
        tweet_id="1",
        text_content="AI launch today",
        user_handle="techmaker",
    )
    llm_settings = LLMSettings()
    stub_service = StubLLMService(
        [
            (
                {
                    "reply_text": "Congrats on the AI launch!",
                    "is_relevant": True,
                    "relevance_reason": "Mentions the announcement",
                    "referenced_topics": ["ai", "launch"],
                },
                None,
            )
        ]
    )

    reply_text, metadata = await generate_guarded_reply(
        llm_service=stub_service,
        tweet=tweet,
        llm_settings=llm_settings,
        system_prompt="system",
        style_summary="Keep it upbeat",
        persona_handle="bot",
        inline_media=None,
        banned_terms=None,
        retry_limit=2,
    )

    assert reply_text == "Congrats on the AI launch!"
    assert metadata["attempts"] == 1
    assert metadata["flagged_terms"] == []
    assert len(stub_service.calls) == 1


@pytest.mark.asyncio
async def test_generate_guarded_reply_retries_on_off_topic_terms():
    tweet = ScrapedTweet(
        tweet_id="42",
        text_content="Discussing distributed AI training",
        user_handle="mlresearcher",
    )
    llm_settings = LLMSettings()
    stub_service = StubLLMService(
        [
            (
                {
                    "reply_text": "You should read the OpenAI API docs instead.",
                    "is_relevant": True,
                    "relevance_reason": "Mentions AI APIs",
                    "referenced_topics": ["api"],
                },
                None,
            ),
            (
                {
                    "reply_text": "Distributed training is so compute hungry - great points!",
                    "is_relevant": True,
                    "relevance_reason": "References distributed training",
                    "referenced_topics": ["training"],
                },
                None,
            ),
        ]
    )

    reply_text, metadata = await generate_guarded_reply(
        llm_service=stub_service,
        tweet=tweet,
        llm_settings=llm_settings,
        system_prompt="system",
        style_summary=None,
        persona_handle="mlbot",
        inline_media=None,
        banned_terms=None,
        retry_limit=3,
    )

    assert reply_text == "Distributed training is so compute hungry - great points!"
    assert metadata["attempts"] == 2
    assert len(stub_service.calls) == 2


@pytest.mark.asyncio
async def test_generate_guarded_reply_returns_none_when_all_attempts_fail():
    tweet = ScrapedTweet(
        tweet_id="77",
        text_content="Thoughts on new robotics demo",
        user_handle="roboticist",
    )
    llm_settings = LLMSettings()
    stub_service = StubLLMService(
        [
            (
                {
                    "reply_text": "",
                    "is_relevant": False,
                    "relevance_reason": "Could not form reply",
                    "referenced_topics": [],
                },
                None,
            )
        ]
    )

    reply_text, metadata = await generate_guarded_reply(
        llm_service=stub_service,
        tweet=tweet,
        llm_settings=llm_settings,
        system_prompt="system",
        style_summary=None,
        persona_handle=None,
        inline_media=None,
        banned_terms=None,
        retry_limit=1,
    )

    assert reply_text is None
    assert metadata["attempts"] == 1
    assert "No reply text" in metadata["relevance_reason"]


def test_should_apply_style_profile_requires_keyword_overlap():
    tweet = ScrapedTweet(
        tweet_id="11",
        text_content="Platform engineering teams love detailed runbooks",
        user_handle="opslead",
    )

    assert should_apply_style_profile(tweet, ["platform", "runbooks"]) is True
    assert should_apply_style_profile(tweet, ["gardening"]) is False


def test_should_apply_style_profile_skips_humorous_tweets():
    tweet = ScrapedTweet(
        tweet_id="99",
        text_content="LOL this meme about deploy scripts broke me",
        user_handle="joker",
    )

    assert should_apply_style_profile(tweet, ["deploy", "scripts"]) is False


@pytest.mark.asyncio
async def test_generate_guarded_reply_includes_media_only_guidance():
    tweet = ScrapedTweet(
        tweet_id="media-only",
        text_content="",
        user_handle="visualposter",
        embedded_media_urls=["https://example.com/image.png"],
    )
    llm_settings = LLMSettings()
    inline_media = [
        {
            "role": "user",
            "parts": [
                {
                    "type": "media",
                    "media_type": "image",
                    "source": {"type": "url", "url": "https://example.com/image.png"},
                }
            ],
        }
    ]
    stub_service = StubLLMService(
        [
            (
                {
                    "reply_text": "I can't view the image clearly - can you share more?",
                    "is_relevant": True,
                    "relevance_reason": "Acknowledged lack of visibility",
                    "referenced_topics": [],
                },
                None,
            )
        ]
    )

    reply_text, metadata = await generate_guarded_reply(
        llm_service=stub_service,
        tweet=tweet,
        llm_settings=llm_settings,
        system_prompt="system",
        style_summary=None,
        persona_handle=None,
        inline_media=inline_media,
        banned_terms=None,
        retry_limit=1,
    )

    assert reply_text == "I can't view the image clearly - can you share more?"
    assert metadata["attempts"] == 1
    call = stub_service.calls[0]
    task_instruction = call["task_instruction"]
    assert "[no text supplied]" in task_instruction
    assert "no visible text caption" in task_instruction.lower()
    assert call["inline_media"] == inline_media


@pytest.mark.asyncio
async def test_generate_guarded_reply_inlines_media_for_gemini(monkeypatch):
    captured_urls = []

    async def fake_download(url):  # pragma: no cover - simple test helper
        captured_urls.append(url)
        return "data:image/png;base64,QUFB"

    monkeypatch.setattr(reply_generator, "_download_media_to_data_url", fake_download)

    tweet = ScrapedTweet(
        tweet_id="gemini",
        text_content="",
        user_handle="visualposter",
        embedded_media_urls=["https://example.com/image.png"],
    )
    llm_settings = LLMSettings(service_preference="gemini")
    inline_media = [
        {
            "role": "user",
            "parts": [
                {
                    "type": "media",
                    "media_type": "image",
                    "source": {"type": "url", "url": "https://example.com/image.png"},
                }
            ],
        }
    ]
    stub_service = StubLLMService(
        [
            (
                {
                    "reply_text": "Image acknowledged.",
                    "is_relevant": True,
                    "relevance_reason": "Handled media",
                    "referenced_topics": [],
                },
                None,
            )
        ]
    )

    reply_text, metadata = await generate_guarded_reply(
        llm_service=stub_service,
        tweet=tweet,
        llm_settings=llm_settings,
        system_prompt="system",
        style_summary=None,
        persona_handle=None,
        inline_media=inline_media,
        banned_terms=None,
        retry_limit=1,
    )

    assert reply_text == "Image acknowledged."
    assert metadata["attempts"] == 1
    assert captured_urls == ["https://example.com/image.png"]
    media_source = stub_service.calls[0]["inline_media"][0]["parts"][0]["source"]
    assert media_source["type"] == "data_url"
    assert media_source["data_url"].startswith("data:image/png;base64,QUFB")