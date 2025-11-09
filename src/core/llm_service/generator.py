import logging
from typing import Optional, Dict, Any, List

try:  # LangChain 0.2+ exposes messages via langchain_core
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
except ImportError:  # pragma: no cover - fall back for older langchain versions
    from langchain.schema import HumanMessage, SystemMessage, AIMessage, BaseMessage  # type: ignore

logger = logging.getLogger(__name__)


def _build_user_content(prompt: str, inline_media: List[Dict[str, Any]]) -> Any:  # type: ignore[valid-type]
    text_prompt = (prompt or "").strip()
    if not inline_media:
        return text_prompt

    content: List[Dict[str, Any]] = []
    if text_prompt:
        content.append({"type": "text", "text": text_prompt})

    for media in inline_media:
        parts = media.get('parts', []) if isinstance(media, dict) else []
        for part in parts:
            part_type = part.get('type') if isinstance(part, dict) else None
            if part_type == 'text':
                text_value = str(part.get('text', '')).strip()
                if text_value:
                    content.append({"type": "text", "text": text_value})
            elif part_type == 'media':
                source = part.get('source') if isinstance(part, dict) else None
                if not isinstance(source, dict):
                    continue
                url = source.get('url')
                if not url:
                    continue
                content.append({
                    "type": "image_url",
                    "image_url": {"url": str(url)},
                })

    if not content:
        fallback_text = text_prompt or "Please respond appropriately to the provided media."
        content.append({"type": "text", "text": fallback_text})

    return content


class TextGenerator:
    """
    Service-agnostic text generation with fallback across providers.
    Expects pre-initialized clients and llm settings.
    """

    def __init__(self, clients: Dict[str, Any], llm_settings: Dict[str, Any]):
        self.gemini_client = clients.get('gemini_client')
        self.openai_client = clients.get('openai_client')
        self.azure_openai_client = clients.get('azure_openai_client')
        self.llm_settings = llm_settings or {}
        self.service_preference_order: List[str] = self.llm_settings.get(
            'service_preference_order', ['azure', 'openai', 'gemini']
        )

    async def generate_text(
        self,
        prompt: str,
        *,
        service_preference: Optional[str] = None,
        system_prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        **call_params: Any,
    ) -> Optional[str]:
        services_to_try = list(self.service_preference_order)
        if service_preference and service_preference in services_to_try:
            services_to_try.insert(0, services_to_try.pop(services_to_try.index(service_preference)))
        elif service_preference:
            services_to_try.insert(0, service_preference)

        logger.debug(f"Service attempt order: {services_to_try}")

        for service_name in services_to_try:
            logger.info(f"Attempting to generate text using {service_name}...")
            service_config = self.llm_settings.get(service_name, {})

            final_params = {**service_config.get('default_params', {}), **call_params}
            if 'model_name' in final_params and 'model' not in final_params:
                final_params['model'] = final_params.pop('model_name')
            if 'max_tokens' not in final_params:
                final_params['max_tokens'] = self.llm_settings.get('default_max_tokens', 250)

            inline_media_payload: List[Dict[str, Any]] = final_params.pop('inline_media', []) or []

            try:
                if service_name == 'gemini' and self.gemini_client:
                    model_to_use = final_params.pop('model', service_config.get('model', 'gemini-2.5-pro'))
                    if 'max_tokens' in final_params and 'max_output_tokens' not in final_params:
                        final_params['max_output_tokens'] = final_params.pop('max_tokens')

                    gemini_messages: List[BaseMessage] = []
                    if system_prompt:
                        gemini_messages.append(SystemMessage(content=system_prompt.strip()))

                    user_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
                    for media in inline_media_payload:
                        try:
                            media_parts = media.get('parts', []) or []
                            for part in media_parts:
                                part_type = part.get('type')
                                if part_type == 'text':
                                    text_value = str(part.get('text', '')).strip()
                                    if text_value:
                                        user_parts.append({"type": "text", "text": text_value})
                                elif part_type == 'media':
                                    source = part.get('source') or {}
                                    url = source.get('url')
                                    if url:
                                        # Gemini expects web images as "image_url" entries when provided via LangChain messages
                                        user_parts.append({"type": "image_url", "image_url": {"url": str(url)}})
                        except Exception as media_error:
                            logger.error(
                                f"Failed to attach inline media to Gemini request: {media_error}",
                                exc_info=True,
                            )

                    gemini_messages.append(HumanMessage(content=user_parts))

                    response = await self.gemini_client.ainvoke(gemini_messages, **final_params)
                    logger.info(f"Successfully generated text using Gemini model '{model_to_use}'.")
                    if isinstance(response, AIMessage):
                        return response.content
                    if hasattr(response, 'content'):
                        return response.content
                    return str(response)

                elif service_name == 'azure' and self.azure_openai_client:
                    deployment_name = final_params.pop(
                        'model', service_config.get('deployment_name')
                    )
                    if not deployment_name:
                        logger.error("Azure deployment name not specified for Azure OpenAI call.")
                        continue
                    built_messages = messages[:] if messages is not None else []
                    if messages is None and system_prompt:
                        built_messages.append({"role": "system", "content": system_prompt})

                    user_content = _build_user_content(prompt, inline_media_payload)
                    if messages is None:
                        built_messages.append({"role": "user", "content": user_content})
                    else:
                        built_messages.append({"role": "user", "content": user_content})

                    response = await self.azure_openai_client.chat.completions.create(
                        model=deployment_name,
                        messages=built_messages,
                        **final_params,
                    )
                    logger.info(f"Successfully generated text using Azure OpenAI deployment '{deployment_name}'.")
                    return response.choices[0].message.content.strip()

                elif service_name == 'openai' and self.openai_client:
                    model_to_use = final_params.pop('model', service_config.get('model', 'gpt-3.5-turbo'))
                    built_messages = messages[:] if messages is not None else []
                    if messages is None and system_prompt:
                        built_messages.append({"role": "system", "content": system_prompt})

                    user_content = _build_user_content(prompt, inline_media_payload)
                    built_messages.append({"role": "user", "content": user_content})

                    response = await self.openai_client.chat.completions.create(
                        model=model_to_use,
                        messages=built_messages,
                        **final_params,
                    )
                    logger.info(f"Successfully generated text using OpenAI model '{model_to_use}'.")
                    return response.choices[0].message.content.strip()

                elif service_name not in ['gemini', 'azure', 'openai']:
                    if service_preference == service_name:
                        logger.warning(f"Unknown LLM service preference: {service_name}")
                else:
                    logger.info(f"{service_name.capitalize()} client not available or not initialized. Skipping.")

            except Exception as e:
                logger.error(f"Error using {service_name} LLM: {e}", exc_info=True)

        logger.error("All configured LLM services failed or none are available/configured to generate text.")
        return None

