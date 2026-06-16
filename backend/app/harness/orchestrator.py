"""
AI Harness: Orchestrator
核心编排层 - 统一入口，协调 PromptRegistry / ContextManager / ModelRouter / Guardrails
支持：单次调用 / 流式调用 / 多步编排
"""
import json
import asyncio
import logging
from typing import AsyncGenerator, Any

import openai
import httpx

from .prompt_templates import prompt_registry
from .model_router import model_router, guardrails, GuardrailError
from .context_manager import get_context
from .config_loader import get_ai_config, get_task_timeout
from .analysis_schema import normalize_chat_analysis

client_cache: dict[str, openai.AsyncOpenAI] = {}
provider_client_signatures: dict[str, str] = {}
_http_client: httpx.AsyncClient | None = None
logger = logging.getLogger("import")


def resolve_provider_name(task_name: str) -> str:
    return model_router.resolve_provider(task_name)


def resolve_provider_config(provider_name: str) -> dict[str, Any]:
    providers_config = get_ai_config().get("providers", {}) or {}
    provider = providers_config.get(provider_name, {})
    if provider:
        return provider
    return providers_config.get("deepseek", {}) or {}


def get_async_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=180.0, connect=30.0),
        )
    return _http_client


def get_openai_client(provider_name: str) -> openai.AsyncOpenAI:
    provider_config = resolve_provider_config(provider_name)
    api_key = provider_config.get("api_key") or None
    base_url = provider_config.get("base_url")
    signature = f"{provider_name}|{base_url or ''}|{api_key or ''}"
    cached_signature = provider_client_signatures.get(provider_name)
    if cached_signature == signature:
        client = client_cache.get(signature)
        if client is not None:
            return client
    client_kwargs: dict[str, Any] = {
        "http_client": get_async_http_client(),
        "api_key": api_key or "not-used",
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(**client_kwargs)
    client_cache[signature] = client
    provider_client_signatures[provider_name] = signature
    return client


class AIOrchestrator:
    """
    AI Harness 主调度器
    所有 AI 调用都经过此类，确保：
    - 统一的 Prompt 管理
    - 模型路由
    - 输出校验
    - 上下文管理
    - 任务级超时（config.yaml ai.task_timeouts）
    """

    def _resolve_model_for_provider(self, task_name: str, provider_name: str) -> str | None:
        """为「兜底供应商」算出该任务应使用的模型（按任务复杂度取该 provider 的模型分级）。"""
        ai_config = get_ai_config()
        pconf = (ai_config.get("providers", {}) or {}).get(provider_name) or {}
        if not pconf:
            return None
        complexity = model_router.TASK_MAP.get(task_name)
        complexity_val = complexity.value if complexity else "medium"
        models = pconf.get("models", {}) or {}
        return (ai_config.get("task_models", {}) or {}).get(task_name) or models.get(complexity_val)

    async def _create_completion(self, task_name: str, client, request_kwargs: dict[str, Any], provider_name: str = ""):
        timeout = get_task_timeout(task_name)
        try:
            return await asyncio.wait_for(
                client.chat.completions.create(**request_kwargs),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, openai.APIConnectionError, openai.APITimeoutError,
                openai.InternalServerError, openai.RateLimitError) as exc:
            # 主供应商连接/超时/限流/5xx → 自动切到 config 的 fallback_provider 重试一次
            fb = (get_ai_config().get("fallback_provider") or "").strip()
            providers_config = get_ai_config().get("providers", {}) or {}
            if not fb or fb == provider_name or fb not in providers_config:
                raise
            fb_model = self._resolve_model_for_provider(task_name, fb)
            if not fb_model:
                raise
            logger.warning("主供应商失败，切兜底 provider=%s→%s model=%s task=%s err=%s",
                           provider_name or "?", fb, fb_model, task_name, exc)
            fb_client = get_openai_client(fb)
            fb_kwargs = {**request_kwargs, "model": fb_model}
            return await asyncio.wait_for(
                fb_client.chat.completions.create(**fb_kwargs),
                timeout=timeout,
            )

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

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            raw = ""
            finish_reason = None
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
                response = await self._create_completion(task_name, client, request_kwargs, model_cfg.provider)
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
                last_error = e
                logger.warning(
                    "AI 输出校验失败 task=%s provider=%s model=%s attempt=%s finish_reason=%s raw_len=%s raw_tail=%s error=%s",
                    task_name,
                    model_cfg.provider,
                    model_cfg.model,
                    attempt + 1,
                    finish_reason,
                    len(raw),
                    raw[-160:],
                    e,
                )
                if attempt == retries:
                    raise
                # 把字段级错误回传给下一次重试，显著提高自我修复成功率
                messages = messages + [
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": f"上一次输出未通过校验：{e}。请严格按照 system 中的 JSON 结构重新输出完整 JSON。"},
                ]
                await asyncio.sleep(0.5)
            except Exception as e:
                last_error = e
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
        raise last_error or RuntimeError(f"AI 调用失败：{task_name}")

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
                response = await self._create_completion(
                    task_name,
                    client,
                    {
                        "model": model_cfg.model,
                        "max_tokens": model_cfg.max_tokens,
                        "temperature": model_cfg.temperature,
                        "messages": openai_messages,
                    },
                    model_cfg.provider,
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
        viewers_block: str = "",
        goal: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天分析（表层回复流式 + 主接收方结构化分析 + 多视角分析）
        Yields: SSE data chunks (JSON strings)
        状态机更新由调用方（chat.py）基于 done 结果执行，本层不写状态。
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
        memory_blocks = "\n\n".join(
            block for block in [character_memory, speaker_state_block, listener_state_block, consistency_block] if block
        )
        messages, system = ctx.build_messages(
            surface_prompt["system"], surface_prompt["user"], memory_blocks
        )

        try:
            openai_messages = [{"role": "system", "content": system}] + messages
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=surface_cfg.model,
                    max_tokens=surface_cfg.max_tokens,
                    temperature=surface_cfg.temperature,
                    messages=openai_messages,
                    stream=True,
                ),
                timeout=get_task_timeout("chat_surface_reply"),
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
                character_memory=memory_blocks,
            )

            result = normalize_chat_analysis(analysis_result if isinstance(analysis_result, dict) else {})
            if not result.get("reply"):
                result["reply"] = surface_reply.strip()

            # 多视角分析：在场每个旁观角色站在自己立场分析这句话
            if viewers_block:
                try:
                    perspectives = await self.analyze_multi_perspective(
                        scenario=scenario, speaker=speaker, content=content,
                        viewers_block=viewers_block, context=ctx.to_text(8),
                        memory_block=character_memory, goal=goal,
                    )
                    result["perspectives"] = perspectives
                except Exception as exc:
                    logger.warning("多视角分析失败 speaker=%s error=%s", speaker, exc)
                    result["perspectives"] = []
            else:
                result["perspectives"] = []

            yield json.dumps({"type": "done", "result": result})
        except GuardrailError as e:
            yield json.dumps({"type": "error", "message": str(e)})
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)})

    async def analyze_multi_perspective(
        self, scenario: str, speaker: str, content: str, viewers_block: str, context: str,
        memory_block: str = "", goal: str = "", dynamics: str = "",
    ) -> list[dict]:
        """多视角分析：在场每个旁观角色对这句话的独立分析。返回 normalize 后的 perspective 列表。
        memory_block 注入向量语义召回的相关历史/证据；goal 给定时让「我」的 moves 围绕目标排序；
        dynamics 是确定性算出的对话动态硬提示（重复/连发未回应/反常），强制分析随对话变化。"""
        result = await self.call(
            "multi_perspective_analysis",
            {
                "scenario": scenario, "speaker": speaker, "content": content,
                "viewers_block": viewers_block, "context": context or "（对话开始）",
                "memory_block": memory_block or "（暂无相关历史记忆）",
                "goal": goal or "（未指定具体目标，给出通用而稳妥的应对即可）",
                "dynamics": dynamics or "（无特殊动态，按正常对话分析）",
            },
            retries=1,
        )
        raw = result.get("perspectives") if isinstance(result, dict) else None
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            viewer = (item.get("viewer") or "").strip()
            if not viewer:
                continue
            normalized = normalize_chat_analysis(item)
            normalized["viewer"] = viewer
            stance = (item.get("stance") or "observer").strip()
            normalized["stance"] = "speaker" if stance == "speaker" else "observer"
            out.append(normalized)
        return out

    async def critique_perspectives(self, utterance: str, perspectives_payload: list, evidence_block: str = "") -> dict:
        """多视角分析的 LLM 复核(critic-revise)：逐视角审查过度推断/引用不实，回传修订与问题清单。
        这是确定性接地核查之上的更深一层——确定性层只验证引用是否真实，本层判断结论是否超出原文支撑。"""
        result = await self.call(
            "perspective_critic_revise",
            {
                "utterance": utterance,
                "perspectives": json.dumps(perspectives_payload, ensure_ascii=False),
                "evidence_block": evidence_block or "（无额外证据，仅依据发言原文判断）",
            },
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def analyze_theory_of_mind(self, me: str, counterpart: str, counterpart_block: str, dialogue: str) -> dict:
        """信息差/心智模型：推断对方知道什么、不知道什么、在隐瞒什么、对我抱有哪些假设。"""
        result = await self.call(
            "theory_of_mind",
            {"me": me, "counterpart": counterpart, "counterpart_block": counterpart_block or "（档案有限）", "dialogue": dialogue or "（暂无对话）"},
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def predict_counterfactual(self, me: str, counterpart: str, candidate: str, counterpart_block: str, memory_block: str, context: str, goal: str = "") -> dict:
        """反事实预测：如果我对对方说出 candidate，预测他的反应/情绪/达成目标的可能性。"""
        result = await self.call(
            "counterfactual_predict",
            {
                "me": me, "counterpart": counterpart, "candidate": candidate,
                "counterpart_block": counterpart_block or "（档案有限）",
                "memory_block": memory_block or "（无相关历史）",
                "context": context or "（对话开始）",
                "goal": goal or "（未指定，按推进当前互动评估）",
            },
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def assess_goal_progress(self, me: str, goal: str, prev_state: str, new_dialogue: str) -> dict:
        """目标进度：只评估新发生的对话相对目标推进/停滞/倒退，并在此前进度上更新总分。"""
        result = await self.call(
            "goal_progress_review",
            {
                "me": me or "我", "goal": goal,
                "prev_state": prev_state or "（尚无，刚开始追踪，进度从 0 起步）",
                "new_dialogue": new_dialogue or "（暂无新对话）",
            },
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def review_prediction(self, me: str, counterpart: str, candidate: str,
                                pred_reaction: str, pred_reply: str, pred_success, actual_reply: str) -> dict:
        """预演闭环：对照"当时的预测"与"对方实际回复"，判定准不准 + 提炼对这个人的教训。"""
        result = await self.call(
            "prediction_review",
            {
                "me": me, "counterpart": counterpart, "candidate": candidate,
                "pred_reaction": pred_reaction or "（未知）",
                "pred_reply": pred_reply or "（无）",
                "pred_success": pred_success if pred_success is not None else "（未知）",
                "actual_reply": actual_reply or "（对方未回复）",
            },
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def debate_perspective(self, speaker: str, utterance: str, current_read: str, evidence_block: str = "") -> dict:
        """多轮对抗：对某句话的主流解读跑"魔鬼代言人 + 调和"，产出最强反面解读 + 调和后终版。
        返回 {alternative_read, stronger, reconciled}。失败/无效时返回空 dict。"""
        result = await self.call(
            "perspective_debate",
            {
                "speaker": speaker or "对方",
                "utterance": utterance,
                "current_read": current_read or "（暂无主流解读）",
                "evidence_block": evidence_block or "（无额外证据，仅凭原话）",
            },
            retries=1,
        )
        return result if isinstance(result, dict) else {}

    async def infer_quick_profile(self, name: str, dialogue: str, scenario: str = "") -> list[dict]:
        """冷启动破局：档案为空时，仅据本会话对话推断某人的临时侧写（不落主档案）。
        返回 [{category, content, evidence}, ...]，每条都要有对话原话支撑。"""
        result = await self.call(
            "quick_profile_infer",
            {"name": name, "scenario": scenario or "日常对话", "dialogue": dialogue or "（暂无对话）"},
            retries=1,
        )
        facts = result.get("facts") if isinstance(result, dict) else None
        if not isinstance(facts, list):
            return []
        out = []
        for f in facts:
            if isinstance(f, dict) and (f.get("content") or "").strip():
                out.append({
                    "category": (f.get("category") or "").strip(),
                    "content": (f.get("content") or "").strip(),
                    "evidence": (f.get("evidence") or "").strip(),
                })
        return out

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

    async def summarize_context(self, previous_summary: str, dialogue: str) -> str:
        return await self.call_text(
            "context_summary",
            {
                "previous_summary": previous_summary or "（无）",
                "dialogue": dialogue,
            },
            retries=1,
        )

    async def parse_import_content(self, file_type: str, content_text: str) -> dict:
        if file_type == "profile_document":
            return await self.call(
                "import_profile_document_parse",
                {"content_text": content_text[:12000]},
                retries=1,
            )
        task_name = "import_narrative_parse" if file_type == "narrative" else "import_dialogue_parse"
        return await self.call(
            task_name,
            {
                "file_type": file_type,
                "content_text": content_text[:12000],
            },
            retries=1,
        )

    async def analyze_relationship_deep(
        self,
        pair_profiles: str,
        interaction_samples: str,
        existing_relationship: str,
    ) -> dict:
        """关系深度分析：权力结构 / 互动模式 / 认知差 / 张力 / 演化叙事"""
        return await self.call(
            "relationship_deep_analysis",
            {
                "pair_profiles": pair_profiles,
                "interaction_samples": interaction_samples or "（无直接对话记录，基于事实与事件推断）",
                "existing_relationship": existing_relationship or "（暂无关系记录）",
            },
            retries=1,
        )

    async def update_trait_hypotheses(
        self,
        character_profile: str,
        active_hypotheses: str,
        new_evidence: str,
    ) -> dict:
        """特质假设演化：新证据对照活跃假设 → 支持/反驳/新假设"""
        return await self.call(
            "trait_hypothesis_update",
            {
                "character_profile": character_profile,
                "active_hypotheses": active_hypotheses or "（暂无活跃假设）",
                "new_evidence": new_evidence,
            },
            retries=1,
        )

    async def rebuild_import_analysis(
        self,
        interaction_unit: dict,
        context_payload: dict,
        context_window: list | None = None,
    ) -> dict:
        return await self.call(
            "interaction_analysis_rebuild",
            {
                "interaction_unit": json.dumps(interaction_unit, ensure_ascii=False),
                "context_window": json.dumps(context_window or [], ensure_ascii=False),
                "context_payload": json.dumps(context_payload, ensure_ascii=False),
            },
        )

    async def analyze_interaction_batch(
        self,
        character_profiles: str,
        relationships: str,
        context_summary: str,
        dialogue_block: str,
        count: int,
    ) -> dict:
        """批量深度分析：一次调用分析连续多句对话（带全部角色档案与关系上下文）"""
        return await self.call(
            "interaction_batch_analysis",
            {
                "character_profiles": character_profiles or "（暂无档案）",
                "relationships": relationships or "（暂无关系记录）",
                "context_summary": context_summary or "（本段为开头，无此前剧情）",
                "dialogue_block": dialogue_block,
                "count": count,
            },
            retries=1,
        )

    async def generate_import_profile(
        self,
        name: str,
        current_profile: str,
        dialogue_samples: str,
        event_samples: str,
        relationship_samples: str,
        rule_hints: str,
    ) -> dict:
        """融合模式：当前档案 + 本次导入的新证据 → 深化后的完整档案（支持多次导入渐进完善）"""
        return await self.call(
            "import_profile_gen",
            {
                "name": name,
                "current_profile": current_profile or "（暂无档案，本次为首次构建）",
                "dialogue_samples": dialogue_samples or "（无台词样本）",
                "event_samples": event_samples or "（无事件记录）",
                "relationship_samples": relationship_samples or "（无关系线索）",
                "rule_hints": rule_hints or "（无）",
            },
            retries=1,
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
