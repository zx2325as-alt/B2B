"""
AI Harness: Orchestrator
核心编排层 - 统一入口，协调 PromptRegistry / ContextManager / ModelRouter / Guardrails
支持：单次调用 / 流式调用 / 多步编排
"""
import json
import asyncio
from typing import AsyncGenerator, Any

import anthropic

from .prompt_templates import prompt_registry
from .model_router import model_router, guardrails, GuardrailError
from .context_manager import get_context


client = anthropic.AsyncAnthropic()


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
                response = await client.messages.create(
                    model=model_cfg.model,
                    max_tokens=model_cfg.max_tokens,
                    temperature=model_cfg.temperature,
                    system=system,
                    messages=messages,
                )
                raw = response.content[0].text
                result = guardrails.process(task_name, raw)
                return result
            except GuardrailError as e:
                if attempt == retries:
                    raise
                await asyncio.sleep(0.5)
            except anthropic.APIError as e:
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
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天分析
        Yields: SSE data chunks (JSON strings)
        """
        prompt = prompt_registry.render(
            "chat_analysis",
            scenario=scenario,
            characters=characters_desc,
            speaker=speaker,
            content=content,
        )
        model_cfg = model_router.route("chat_analysis", len(content))
        ctx = get_context(conversation_id)
        messages, system = ctx.build_messages(
            prompt["system"], prompt["user"], character_memory
        )

        collected = ""
        async with client.messages.stream(
            model=model_cfg.model,
            max_tokens=model_cfg.max_tokens,
            temperature=model_cfg.temperature,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                collected += text
                yield json.dumps({"type": "delta", "text": text})

        # 流结束后解析完整 JSON
        try:
            result = guardrails.process("chat_analysis", collected)
            ctx.add("user", content, {"character_name": speaker})
            ctx.add("assistant", result.get("reply", ""), {"character_name": "AI"})
            yield json.dumps({"type": "done", "result": result})
        except GuardrailError as e:
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


orchestrator = AIOrchestrator()
