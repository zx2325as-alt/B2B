"""
AI Harness: Model Router + Guardrails
- Model Router: 根据任务复杂度选择模型（配置实时生效，无需重启）
- Guardrails: 输出格式校验（含嵌套结构校验）+ 截断 JSON 修复
"""
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .config_loader import get_ai_config

# ─── Model Router ─────────────────────────────────────────────────────────────

class TaskComplexity(str, Enum):
    SIMPLE = "simple"       # 简单问答、格式化
    MEDIUM = "medium"       # 情绪分析、关系分析
    COMPLEX = "complex"     # 深度心理剖析、多角色建模


@dataclass
class ModelConfig:
    provider: str
    model: str
    max_tokens: int
    temperature: float


class ModelRouter:
    """
    根据 Prompt 类型或内容长度自动路由到合适的模型
    """

    TASK_MAP: dict[str, TaskComplexity] = {
        "chat_surface_reply": TaskComplexity.MEDIUM,
        "chat_analysis": TaskComplexity.MEDIUM,
        "multi_perspective_analysis": TaskComplexity.COMPLEX,
        "import_dialogue_parse": TaskComplexity.COMPLEX,
        "import_narrative_parse": TaskComplexity.COMPLEX,
        "import_profile_document_parse": TaskComplexity.COMPLEX,
        "import_commit_review": TaskComplexity.COMPLEX,
        "interaction_analysis_rebuild": TaskComplexity.COMPLEX,
        "interaction_batch_analysis": TaskComplexity.COMPLEX,
        "character_profile_gen": TaskComplexity.COMPLEX,
        "import_profile_gen": TaskComplexity.COMPLEX,
        "relationship_deep_analysis": TaskComplexity.COMPLEX,
        "trait_hypothesis_update": TaskComplexity.COMPLEX,
        "relationship_analysis": TaskComplexity.MEDIUM,
        "ai_suggest_update": TaskComplexity.COMPLEX,
        "emotion_curve": TaskComplexity.SIMPLE,
        "structured_diagnosis": TaskComplexity.COMPLEX,
        "diagnosis_critic": TaskComplexity.COMPLEX,
        "long_context_review": TaskComplexity.COMPLEX,
        "long_context_review_critic": TaskComplexity.COMPLEX,
        "context_summary": TaskComplexity.SIMPLE,
    }

    JSON_TASKS = {
        "chat_analysis",
        "multi_perspective_analysis",
        "import_dialogue_parse",
        "import_narrative_parse",
        "import_profile_document_parse",
        "import_commit_review",
        "interaction_analysis_rebuild",
        "interaction_batch_analysis",
        "character_profile_gen",
        "import_profile_gen",
        "relationship_deep_analysis",
        "trait_hypothesis_update",
        "relationship_analysis",
        "ai_suggest_update",
        "emotion_curve",
        "structured_diagnosis",
        "diagnosis_critic",
        "long_context_review",
        "long_context_review_critic",
    }

    def resolve_provider(self, task_name: str) -> str:
        ai_config = get_ai_config()
        providers_config = ai_config.get("providers", {}) or {}
        task_providers = ai_config.get("task_providers", {}) or {}
        default_provider = ai_config.get("default_provider", "deepseek")
        candidate = task_providers.get(task_name) or default_provider or "deepseek"
        if candidate in providers_config:
            return candidate
        if "deepseek" in providers_config:
            return "deepseek"
        return next(iter(providers_config.keys()), "deepseek")

    def route(self, task_name: str, content_length: int = 0) -> ModelConfig:
        ai_config = get_ai_config()
        complexity = self.TASK_MAP.get(task_name, TaskComplexity.MEDIUM)

        # 内容超长时升级复杂度
        if content_length > 2000 and complexity == TaskComplexity.SIMPLE:
            complexity = TaskComplexity.MEDIUM
        elif content_length > 5000:
            complexity = TaskComplexity.COMPLEX

        provider_name = self.resolve_provider(task_name)
        providers_config = ai_config.get("providers", {}) or {}
        models_config = (providers_config.get(provider_name, {}) or {}).get("models", {}) or {}
        model_name = (
            (ai_config.get("task_models", {}) or {}).get(task_name)
            or models_config.get(complexity.value)
            or "deepseek-chat"
        )
        base_tokens = {
            TaskComplexity.SIMPLE: 512,
            TaskComplexity.MEDIUM: 1024,
            TaskComplexity.COMPLEX: 2048,
        }
        base_temperatures = {
            TaskComplexity.SIMPLE: 0.3,
            TaskComplexity.MEDIUM: 0.5,
            TaskComplexity.COMPLEX: 0.7,
        }
        task_max_tokens = ai_config.get("task_max_tokens", {}) or {}
        task_temperatures = ai_config.get("task_temperatures", {}) or {}
        return ModelConfig(
            provider=provider_name,
            model=model_name,
            max_tokens=int(task_max_tokens.get(task_name, base_tokens[complexity])),
            temperature=float(task_temperatures.get(task_name, base_temperatures[complexity])),
        )

    def requires_json_mode(self, task_name: str) -> bool:
        return task_name in self.JSON_TASKS


model_router = ModelRouter()


# ─── Guardrails ───────────────────────────────────────────────────────────────

class GuardrailError(Exception):
    pass


class OutputGuardrails:
    """
    输出校验护栏
    - JSON 提取与截断修复
    - 顶层必填字段校验
    - 嵌套结构校验（chat_analysis 等结构化协议）
    """

    REQUIRED_FIELDS: dict[str, list[str]] = {
        "chat_analysis": ["reply", "inner_monologue", "emotions", "strategy", "tags"],
        "multi_perspective_analysis": ["perspectives"],
        "character_profile_gen": ["personality_tags", "core_traits", "weakness", "motivation"],
        "import_profile_gen": ["personality_tags", "core_traits", "weakness", "motivation", "speaking_style"],
        "interaction_batch_analysis": ["analyses"],
        "import_profile_document_parse": ["subject", "persona_facts"],
        "relationship_deep_analysis": ["power_dynamic", "interaction_pattern", "tensions", "trajectory"],
        "trait_hypothesis_update": ["updates", "new_hypotheses"],
        "relationship_analysis": ["relationship_summary", "predicted_trend"],
        "emotion_curve": ["emotions", "trend"],
        "ai_suggest_update": ["updates"],
        "structured_diagnosis": ["summary", "confidence", "supporting_evidence", "conflicting_evidence", "alternative_explanations", "insufficient_evidence"],
        "diagnosis_critic": ["final_status", "confidence_adjustment", "issues", "revised_summary"],
        "long_context_review": ["summary", "confidence", "candidate_profile", "profile_updates", "consolidated_memories", "contradictions"],
        "long_context_review_critic": ["final_status", "confidence_adjustment", "issues", "approved_update_indexes", "approved_memory_indexes"],
    }

    # 嵌套结构要求：{字段: {子字段: 类型}}；类型为 None 表示只要求存在
    NESTED_FIELDS: dict[str, dict[str, dict[str, type | None]]] = {
        "chat_analysis": {
            "inner_monologue": {"first_reaction": str, "defense": str, "tendency": str},
            "emotions": {"intended": dict, "surface": dict, "deep": dict, "suppressed": dict},
            "strategy": {"short_term": str, "long_term": str, "consistency_note": str},
            "tags": {"primary": str, "secondary": str, "relation": str},
        },
    }

    def _balance_json_suffix(self, text: str) -> str:
        stack: list[str] = []
        in_string = False
        escaped = False
        for char in text:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in {"}", "]"} and stack and stack[-1] == char:
                stack.pop()
        suffix = '"' if in_string else ""
        suffix += "".join(reversed(stack))
        return suffix

    def _repair_partial_json(self, text: str) -> Any | None:
        boundary_indexes = [
            index
            for index, char in enumerate(text)
            if char in {",", "}", "]"}
        ]
        boundary_indexes.append(len(text) - 1)
        tried = set()
        for index in reversed(boundary_indexes[-80:]):
            candidate = text[: index + 1].rstrip()
            if not candidate:
                continue
            if candidate[-1] == ",":
                candidate = candidate[:-1].rstrip()
            candidate = candidate + self._balance_json_suffix(candidate)
            if candidate in tried:
                continue
            tried.add(candidate)
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    def extract_json(self, text: str) -> Any:
        clean = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"[\[\{].*[\]\}]", clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            start_match = re.search(r"[\[\{]", clean)
            if start_match:
                repaired = self._repair_partial_json(clean[start_match.start():])
                if repaired is not None:
                    return repaired
            raise GuardrailError(f"无法解析 JSON 输出: {text[:200]}")

    def validate(self, task_name: str, output: Any) -> Any:
        required = self.REQUIRED_FIELDS.get(task_name, [])
        if required:
            if not isinstance(output, dict):
                raise GuardrailError(f"期望 dict 输出，实际: {type(output)}")
            missing = [f for f in required if f not in output]
            if missing:
                raise GuardrailError(f"输出缺少必填字段: {missing}")
        nested = self.NESTED_FIELDS.get(task_name, {})
        for field, children in nested.items():
            value = output.get(field)
            if not isinstance(value, dict):
                raise GuardrailError(f"字段 {field} 应为对象，实际: {type(value)}")
            for child, expected_type in children.items():
                if child not in value:
                    raise GuardrailError(f"字段 {field}.{child} 缺失")
                if expected_type is not None and not isinstance(value[child], expected_type):
                    raise GuardrailError(
                        f"字段 {field}.{child} 类型错误：期望 {expected_type.__name__}，实际 {type(value[child]).__name__}"
                    )
        return output

    def process(self, task_name: str, raw_output: str) -> Any:
        parsed = self.extract_json(raw_output)
        return self.validate(task_name, parsed)


guardrails = OutputGuardrails()
