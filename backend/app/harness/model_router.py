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
        "ai_suggest_update": [],  # array
    }

    FORBIDDEN_PATTERNS = [
        r"ignore (all |previous |above )?instructions",
        r"system prompt",
        r"jailbreak",
    ]

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
            for f in required:
                if f not in output:
                    raise GuardrailError(f"输出缺少必填字段: {f}")
        return output

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
