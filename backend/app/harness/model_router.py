"""
AI Harness: Model Router + Guardrails
- Model Router: 根据任务复杂度选择模型
- Guardrails: 输出格式校验 + 内容安全
"""
import json
import re
import yaml
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Any

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
providers_config = ai_config.get("providers", {})
task_providers = ai_config.get("task_providers", {})
task_models = ai_config.get("task_models", {})
task_max_tokens = ai_config.get("task_max_tokens", {})
task_temperatures = ai_config.get("task_temperatures", {})

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

    # 哪些 prompt 类型使用什么复杂度
    TASK_MAP: dict[str, TaskComplexity] = {
        "chat_surface_reply": TaskComplexity.MEDIUM,
        "chat_analysis": TaskComplexity.MEDIUM,
        "import_dialogue_parse": TaskComplexity.COMPLEX,
        "import_narrative_parse": TaskComplexity.COMPLEX,
        "import_profile_synthesis": TaskComplexity.COMPLEX,
        "import_commit_review": TaskComplexity.COMPLEX,
        "interaction_analysis_rebuild": TaskComplexity.COMPLEX,
        "character_profile_gen": TaskComplexity.COMPLEX,
        "relationship_analysis": TaskComplexity.MEDIUM,
        "ai_suggest_update": TaskComplexity.COMPLEX,
        "emotion_curve": TaskComplexity.SIMPLE,
    }

    JSON_TASKS = {
        "chat_analysis",
        "import_dialogue_parse",
        "import_narrative_parse",
        "import_profile_synthesis",
        "import_commit_review",
        "interaction_analysis_rebuild",
        "character_profile_gen",
        "relationship_analysis",
        "emotion_curve",
    }

    def resolve_provider(self, task_name: str) -> str:
        candidate = task_providers.get(task_name) or default_provider_name or "deepseek"
        if candidate in providers_config:
            return candidate
        if "deepseek" in providers_config:
            return "deepseek"
        return next(iter(providers_config.keys()), "deepseek")

    def _provider_models(self, provider_name: str) -> dict[str, str]:
        provider_cfg = providers_config.get(provider_name, {})
        return provider_cfg.get("models", {})

    def route(self, task_name: str, content_length: int = 0) -> ModelConfig:
        complexity = self.TASK_MAP.get(task_name, TaskComplexity.MEDIUM)

        # 内容超长时升级复杂度
        if content_length > 2000 and complexity == TaskComplexity.SIMPLE:
            complexity = TaskComplexity.MEDIUM
        elif content_length > 5000:
            complexity = TaskComplexity.COMPLEX

        provider_name = self.resolve_provider(task_name)
        models_config = self._provider_models(provider_name)
        default_models = {
            TaskComplexity.SIMPLE: "deepseek-chat",
            TaskComplexity.MEDIUM: "deepseek-chat",
            TaskComplexity.COMPLEX: "deepseek-chat",
        }
        model_name = task_models.get(task_name) or models_config.get(complexity.value) or default_models[complexity]
        if task_name in self.JSON_TASKS and provider_name == "deepseek" and model_name == "deepseek-chat":
            model_name = "deepseek-chat"
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
    - JSON 格式校验
    - 必填字段校验
    - 安全内容过滤
    """

    REQUIRED_FIELDS: dict[str, list[str]] = {
        "chat_analysis": ["reply", "inner_monologue", "emotion_label", "emotion_score", "subtext"],
        "character_profile_gen": ["personality_tags", "core_traits", "weakness", "motivation"],
        "relationship_analysis": ["relationship_summary", "predicted_trend"],
        "emotion_curve": ["emotions", "trend"],
        "import_dialogue_parse": ["characters", "interaction_units", "events", "relationships", "plot_summary"],
        "import_narrative_parse": ["characters", "interaction_units", "events", "relationships", "plot_summary"],
        "import_profile_synthesis": ["character_profiles"],
        "ai_suggest_update": [],  # array
    }

    FORBIDDEN_PATTERNS = [
        r"ignore (all |previous |above )?instructions",
        r"system prompt",
        r"jailbreak",
    ]

    def extract_json(self, text: str) -> Any:
        """从模型输出中提取 JSON，容忍 markdown 包装"""
        # 去掉 ```json ... ```
        clean = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            open_braces = clean.count("{")
            close_braces = clean.count("}")
            open_brackets = clean.count("[")
            close_brackets = clean.count("]")
            if open_braces > close_braces or open_brackets > close_brackets:
                raise GuardrailError(f"模型 JSON 输出疑似被截断，无法完整闭合：{text[:200]}")
            # 尝试找第一个 { 或 [
            match = re.search(r"[\[\{].*[\]\}]", clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            raise GuardrailError(f"无法解析 JSON 输出: {text[:200]}")

    def validate(self, task_name: str, output: Any) -> Any:
        required = self.REQUIRED_FIELDS.get(task_name, [])
        if required:
            if not isinstance(output, dict):
                raise GuardrailError(f"期望 dict 输出，实际: {type(output)}")
            for f in required:
                if f not in output:
                    raise GuardrailError(f"输出缺少必填字段: {f}")
        if task_name in {"import_profile_synthesis"}:
            self._validate_import_profiles(output)
        return output

    def _validate_import_profiles(self, output: dict[str, Any]) -> None:
        profiles = output.get("character_profiles")
        if not isinstance(profiles, list):
            raise GuardrailError("character_profiles 必须为数组")
        required_modules = [
            "character_name",
            "source",
            "confidence_overall",
            "basic_info",
            "personality_model",
            "behavior_patterns",
            "core_motivation",
            "core_weakness",
            "speech_style",
            "relationships",
            "event_timeline",
        ]
        for profile in profiles:
            if not isinstance(profile, dict):
                raise GuardrailError("character_profiles 元素必须为对象")
            for field in required_modules:
                if field not in profile:
                    raise GuardrailError(f"角色档案缺少模块: {field}")
            if not isinstance(profile.get("event_timeline"), list) or len(profile.get("event_timeline") or []) < 5:
                raise GuardrailError("event_timeline 少于5条")
            for item in profile.get("behavior_patterns") or []:
                if not isinstance(item, dict):
                    raise GuardrailError("behavior_patterns 元素必须为对象")
                pattern = (item.get("pattern") or "").strip()
                if pattern:
                    if int(item.get("frequency") or 0) < 2:
                        raise GuardrailError("behavior_patterns.frequency 小于2")
                    if not (item.get("trigger") or "").strip():
                        raise GuardrailError("behavior_patterns.trigger 不能为空")
                    if not (item.get("goal") or "").strip():
                        raise GuardrailError("behavior_patterns.goal 不能为空")
            for item in profile.get("core_motivation") or []:
                if not isinstance(item, dict):
                    raise GuardrailError("core_motivation 元素必须为对象")
                if (item.get("motivation") or "").strip() and len(item.get("evidence") or []) < 2:
                    raise GuardrailError("core_motivation.evidence 少于2条")
            for item in profile.get("core_weakness") or []:
                if not isinstance(item, dict):
                    raise GuardrailError("core_weakness 元素必须为对象")
                if (item.get("weakness") or "").strip() and len(item.get("evidence") or []) < 2:
                    raise GuardrailError("core_weakness.evidence 少于2条")
            concrete_traits = [
                item for item in (profile.get("personality_model") or {}).get("traits", [])
                if isinstance(item, dict) and (item.get("name") or "").strip()
            ]
            if concrete_traits and len(concrete_traits) < 2:
                raise GuardrailError("traits 少于2项")
            for item in concrete_traits:
                if int(item.get("evidence_count") or 0) < 2:
                    raise GuardrailError("trait.evidence_count 小于2")

    def check_safety(self, text: str) -> bool:
        lower = text.lower()
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, lower):
                return False
        return True

    def process(self, task_name: str, raw_output: str) -> Any:
        if not self.check_safety(raw_output):
            raise GuardrailError("输出包含不安全内容")
        parsed = self.extract_json(raw_output)
        return self.validate(task_name, parsed)


guardrails = OutputGuardrails()
