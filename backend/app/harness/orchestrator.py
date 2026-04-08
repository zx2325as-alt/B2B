"""
AI Harness: Orchestrator
核心编排层 - 统一入口，协调 PromptRegistry / ContextManager / ModelRouter / Guardrails
支持：单次调用 / 流式调用 / 多步编排
"""
import json
import asyncio
import os
import yaml
from pathlib import Path
from typing import AsyncGenerator, Any

import openai

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
default_provider_name = ai_config.get("default_provider", "deepseek")
provider_config = ai_config.get("providers", {}).get(default_provider_name, {})

# 优先使用环境变量，如果没有则使用 yaml 配置
api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or provider_config.get("api_key")
base_url = provider_config.get("base_url")

import httpx

client_kwargs = {}
if api_key:
    client_kwargs["api_key"] = api_key
if base_url:
    client_kwargs["base_url"] = base_url

# 添加自定义的 httpx 客户端以配置超时或代理，防止连接超时或拒绝连接
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(timeout=120.0, connect=30.0),
    verify=False # 某些代理环境可能需要
)
client_kwargs["http_client"] = http_client

client = openai.AsyncOpenAI(**client_kwargs)


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
    ) -> dict | list:
        """
        标准单次调用
        Returns: 解析后的 dict 或 list
        """
        prompt = prompt_registry.render(task_name, **template_kwargs)
        user_content = prompt["user"]
        model_cfg = model_router.route(task_name, len(user_content))

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
                # 合并 system prompt 到 messages 中（OpenAI 格式）
                openai_messages = [{"role": "system", "content": system}] + messages
                
                response = await client.chat.completions.create(
                    model=model_cfg.model,
                    max_tokens=model_cfg.max_tokens,
                    temperature=model_cfg.temperature,
                    messages=openai_messages,
                )
                raw = response.choices[0].message.content or ""
                result = guardrails.process(task_name, raw)
                return result
            except GuardrailError as e:
                if attempt == retries:
                    raise
                await asyncio.sleep(0.5)
            except Exception as e:
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
        # ai_suggest_update returns a list
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
        return await self.call(
            "import_dialogue_parse",
            {
                "file_type": file_type,
                "content_text": content_text[:12000],
            },
        )

    async def rebuild_import_analysis(self, interaction_unit: dict, context_payload: dict) -> dict:
        return await self.call(
            "interaction_analysis_rebuild",
            {
                "interaction_unit": json.dumps(interaction_unit, ensure_ascii=False),
                "context_payload": json.dumps(context_payload, ensure_ascii=False),
            },
        )


orchestrator = AIOrchestrator()
