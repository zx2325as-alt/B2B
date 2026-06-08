"""
AI Harness: Orchestrator
核心编排层 - 统一入口，协调 PromptRegistry / ContextManager / ModelRouter / Guardrails
支持：单次调用 / 流式调用 / 多步编排
"""
import json
import asyncio
import logging
import os
import yaml
from pathlib import Path
from typing import AsyncGenerator, Any

import openai
import httpx

from .prompt_templates import prompt_registry
from .model_router import model_router, guardrails, GuardrailError
from .context_manager import get_context
from .state_engine import state_engine


# 读取 YAML 配置文件
CONF_DIR = Path(__file__).parent.parent / "conf"
CONFIG_FILE = CONF_DIR / "config.yaml"

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

config_data = load_config()
ai_config = config_data.get("ai", {})
providers_config = ai_config.get("providers", {})
client_cache: dict[str, openai.AsyncOpenAI] = {}
http_client_cache: dict[str, httpx.AsyncClient] = {}
logger = logging.getLogger("import")


def resolve_provider_name(task_name: str) -> str:
    return model_router.resolve_provider(task_name)


def resolve_provider_config(provider_name: str) -> dict[str, Any]:
    provider = providers_config.get(provider_name, {})
    if provider:
        return provider
    return providers_config.get("deepseek", {})


def resolve_provider_api_key(provider_name: str, provider_config: dict[str, Any]) -> str | None:
    env_keys = {
        "deepseek": ["DEEPSEEK_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "ollama": ["OLLAMA_API_KEY"],
        "vllm": ["VLLM_API_KEY"],
    }
    for env_key in env_keys.get(provider_name, []):
        value = os.environ.get(env_key)
        if value:
            return value
    config_key = provider_config.get("api_key")
    if config_key:
        return config_key
    if provider_name == "openai":
        return os.environ.get("OPENAI_API_KEY")
    if provider_name == "deepseek":
        return os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    return None


def get_async_http_client(provider_name: str) -> httpx.AsyncClient:
    client = http_client_cache.get(provider_name)
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=180.0, connect=30.0),
            verify=False,
        )
        http_client_cache[provider_name] = client
    return client


def get_openai_client(provider_name: str) -> openai.AsyncOpenAI:
    client = client_cache.get(provider_name)
    if client is not None:
        return client
    provider_config = resolve_provider_config(provider_name)
    client_kwargs: dict[str, Any] = {
        "http_client": get_async_http_client(provider_name),
    }
    api_key = resolve_provider_api_key(provider_name, provider_config)
    base_url = provider_config.get("base_url")
    if api_key:
        client_kwargs["api_key"] = api_key
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(**client_kwargs)
    client_cache[provider_name] = client
    return client


class AIOrchestrator:
    """
    AI Harness 主调度器
    所有 AI 调用都经过此类，确保：
    - 统一的 Prompt 管理
    - 模型路由
    - 输出校验
    - 上下文管理
    """

    async def call(
        self,
        task_name: str,
        template_kwargs: dict,
        conversation_id: int | None = None,
        character_memory: str = "",
        retries: int = 2,
        request_overrides: dict[str, Any] | None = None,
    ) -> dict | list:
        """
        标准单次调用
        Returns: 解析后的 dict 或 list
        """
        prompt = prompt_registry.render(task_name, **template_kwargs)
        user_content = prompt["user"]
        model_cfg = model_router.route(task_name, len(user_content))
        client = get_openai_client(model_cfg.provider)

        # 构建消息（含上下文历史）
        if conversation_id is not None:
            ctx = get_context(conversation_id)
            messages, system = ctx.build_messages(
                prompt["system"], user_content, character_memory
            )
        else:
            messages = [{"role": "user", "content": user_content}]
            system = prompt["system"]

        for attempt in range(retries + 1):
            try:
                openai_messages = [{"role": "system", "content": system}] + messages
                request_kwargs: dict[str, Any] = {
                    "model": model_cfg.model,
                    "max_tokens": model_cfg.max_tokens,
                    "temperature": model_cfg.temperature,
                    "messages": openai_messages,
                }
                if model_router.requires_json_mode(task_name):
                    request_kwargs["response_format"] = {"type": "json_object"}
                if request_overrides:
                    request_kwargs.update(request_overrides)
                response = await client.chat.completions.create(**request_kwargs)
                raw = response.choices[0].message.content or ""
                finish_reason = response.choices[0].finish_reason if response.choices else None
                result = guardrails.process(task_name, raw)
                logger.info(
                    "AI 调用成功 task=%s provider=%s model=%s attempt=%s finish_reason=%s raw_len=%s",
                    task_name,
                    model_cfg.provider,
                    model_cfg.model,
                    attempt + 1,
                    finish_reason,
                    len(raw),
                )
                return result
            except GuardrailError as e:
                finish_reason = None
                raw_len = 0
                raw_tail = ""
                try:
                    finish_reason = response.choices[0].finish_reason if response.choices else None
                    raw_len = len(raw)
                    raw_tail = raw[-160:]
                except Exception:
                    pass
                logger.warning(
                    "AI 输出校验失败 task=%s provider=%s model=%s attempt=%s finish_reason=%s raw_len=%s raw_tail=%s error=%s",
                    task_name,
                    model_cfg.provider,
                    model_cfg.model,
                    attempt + 1,
                    finish_reason,
                    raw_len,
                    raw_tail,
                    e,
                )
                if attempt == retries:
                    raise
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(
                    "AI 调用异常 task=%s provider=%s model=%s attempt=%s error=%s",
                    task_name,
                    model_cfg.provider,
                    model_cfg.model,
                    attempt + 1,
                    e,
                )
                if attempt == retries:
                    raise
                await asyncio.sleep(1.0)

    async def call_text(
        self,
        task_name: str,
        template_kwargs: dict,
        conversation_id: int | None = None,
        character_memory: str = "",
        retries: int = 2,
    ) -> str:
        prompt = prompt_registry.render(task_name, **template_kwargs)
        user_content = prompt["user"]
        model_cfg = model_router.route(task_name, len(user_content))
        client = get_openai_client(model_cfg.provider)

        if conversation_id is not None:
            ctx = get_context(conversation_id)
            messages, system = ctx.build_messages(
                prompt["system"], user_content, character_memory
            )
        else:
            messages = [{"role": "user", "content": user_content}]
            system = prompt["system"]

        for attempt in range(retries + 1):
            try:
                openai_messages = [{"role": "system", "content": system}] + messages
                response = await client.chat.completions.create(
                    model=model_cfg.model,
                    max_tokens=model_cfg.max_tokens,
                    temperature=model_cfg.temperature,
                    messages=openai_messages,
                )
                return (response.choices[0].message.content or "").strip()
            except Exception:
                if attempt == retries:
                    raise
                await asyncio.sleep(1.0)

    async def stream_chat(
        self,
        conversation_id: int,
        speaker: str,
        content: str,
        scenario: str = "general",
        characters_desc: str = "",
        character_memory: str = "",
        speaker_state_block: str = "",
        listener_state_block: str = "",
        consistency_block: str = "",
        listener_name: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天分析
        Yields: SSE data chunks (JSON strings)
        """
        surface_prompt = prompt_registry.render(
            "chat_surface_reply",
            scenario=scenario,
            characters=characters_desc,
            speaker=speaker,
            content=content,
        )
        surface_cfg = model_router.route("chat_surface_reply", len(content))
        client = get_openai_client(surface_cfg.provider)
        ctx = get_context(conversation_id)
        messages, system = ctx.build_messages(
            surface_prompt["system"], surface_prompt["user"], "\n\n".join(
                block for block in [character_memory, speaker_state_block, listener_state_block, consistency_block] if block
            )
        )

        try:
            openai_messages = [{"role": "system", "content": system}] + messages
            response = await client.chat.completions.create(
                model=surface_cfg.model,
                max_tokens=surface_cfg.max_tokens,
                temperature=surface_cfg.temperature,
                messages=openai_messages,
                stream=True
            )
            surface_reply = ""
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = delta.content or ""
                if text:
                    surface_reply += text
                    yield json.dumps({"type": "delta", "text": text})

            analysis_result = await self.call(
                "chat_analysis",
                {
                    "scenario": scenario,
                    "characters": characters_desc,
                    "speaker": speaker,
                    "content": content,
                    "generated_reply": surface_reply.strip(),
                },
                conversation_id=conversation_id,
                character_memory="\n\n".join(
                    block for block in [character_memory, speaker_state_block, listener_state_block, consistency_block] if block
                ),
            )

            result = analysis_result if isinstance(analysis_result, dict) else {}
            if not result.get("reply"):
                result["reply"] = surface_reply.strip()
            ctx.add("user", content, {"character_name": speaker})
            ctx.add("assistant", result.get("reply", ""), {"character_name": "AI"})
            if listener_name:
                state_engine.update_after_analysis(
                    conversation_id,
                    speaker,
                    listener_name,
                    result,
                )
            yield json.dumps({"type": "done", "result": result})
        except GuardrailError as e:
            yield json.dumps({"type": "error", "message": str(e)})
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)})

    async def generate_character_profile(self, name: str, role: str, background: str) -> dict:
        return await self.call(
            "character_profile_gen",
            {"name": name, "role": role, "background": background or "无"},
        )

    async def analyze_relationship(
        self, char_a: str, char_b: str, history: list
    ) -> dict:
        return await self.call(
            "relationship_analysis",
            {
                "char_a": char_a,
                "char_b": char_b,
                "history": json.dumps(history, ensure_ascii=False),
            },
        )

    async def suggest_character_update(
        self, current_profile: dict, recent_dialogue: str
    ) -> list:
        result = await self.call(
            "ai_suggest_update",
            {
                "current_profile": json.dumps(current_profile, ensure_ascii=False),
                "recent_dialogue": recent_dialogue,
            },
        )
        if isinstance(result, dict):
            updates = result.get("updates", [])
            return updates if isinstance(updates, list) else []
        return result if isinstance(result, list) else []

    async def analyze_emotion_curve(self, character: str, messages: list[str]) -> dict:
        return await self.call(
            "emotion_curve",
            {
                "character": character,
                "messages": "\n".join(f"{i+1}. {m}" for i, m in enumerate(messages)),
            },
        )

    async def parse_import_content(self, file_type: str, content_text: str) -> dict:
        task_name = "import_narrative_parse" if file_type == "narrative" else "import_dialogue_parse"
        return await self.call(
            task_name,
            {
                "file_type": file_type,
                "content_text": content_text[:12000],
            },
            retries=1,
        )

    async def rebuild_import_analysis(self, interaction_unit: dict, context_payload: dict) -> dict:
        return await self.call(
            "interaction_analysis_rebuild",
            {
                "interaction_unit": json.dumps(interaction_unit, ensure_ascii=False),
                "context_payload": json.dumps(context_payload, ensure_ascii=False),
            },
        )

    async def structured_diagnosis(self, diagnosis_context: dict) -> dict:
        return await self.call(
            "structured_diagnosis",
            {
                "diagnosis_context": json.dumps(diagnosis_context, ensure_ascii=False),
            },
        )

    async def critique_diagnosis(self, diagnosis: dict, evidence_pack: dict, profile_context: dict) -> dict:
        return await self.call(
            "diagnosis_critic",
            {
                "diagnosis": json.dumps(diagnosis, ensure_ascii=False),
                "evidence_pack": json.dumps(evidence_pack, ensure_ascii=False),
                "profile_context": json.dumps(profile_context, ensure_ascii=False),
            },
        )

    async def long_context_review(self, review_corpus: dict) -> dict:
        return await self.call(
            "long_context_review",
            {
                "review_corpus": json.dumps(review_corpus, ensure_ascii=False),
            },
        )

    async def critique_long_context_review(self, review_result: dict, review_corpus_summary: dict) -> dict:
        return await self.call(
            "long_context_review_critic",
            {
                "review_result": json.dumps(review_result, ensure_ascii=False),
                "review_corpus_summary": json.dumps(review_corpus_summary, ensure_ascii=False),
            },
        )


orchestrator = AIOrchestrator()
