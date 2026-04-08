"""
AI Harness: Model Router + Guardrails
- Model Router: 根据任务复杂度选择模型
- Guardrails: 输出格式校验 + 内容安全
"""
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


# ─── Model Router ─────────────────────────────────────────────────────────────

class TaskComplexity(str, Enum):
    SIMPLE = "simple"       # 简单问答、格式化
    MEDIUM = "medium"       # 情绪分析、关系分析
    COMPLEX = "complex"     # 深度心理剖析、多角色建模


@dataclass
class ModelConfig:
    model: str
    max_tokens: int
    temperature: float


MODEL_CONFIGS: dict[TaskComplexity, ModelConfig] = {
    TaskComplexity.SIMPLE: ModelConfig(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        temperature=0.3,
    ),
    TaskComplexity.MEDIUM: ModelConfig(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        temperature=0.5,
    ),
    TaskComplexity.COMPLEX: ModelConfig(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        temperature=0.7,
    ),
}


class ModelRouter:
    """
    根据 Prompt 类型或内容长度自动路由到合适的模型
    """

    # 哪些 prompt 类型使用什么复杂度
    TASK_MAP: dict[str, TaskComplexity] = {
        "chat_analysis": TaskComplexity.MEDIUM,
        "character_profile_gen": TaskComplexity.COMPLEX,
        "relationship_analysis": TaskComplexity.MEDIUM,
        "ai_suggest_update": TaskComplexity.COMPLEX,
        "emotion_curve": TaskComplexity.SIMPLE,
    }

    def route(self, task_name: str, content_length: int = 0) -> ModelConfig:
        complexity = self.TASK_MAP.get(task_name, TaskComplexity.MEDIUM)

        # 内容超长时升级复杂度
        if content_length > 2000 and complexity == TaskComplexity.SIMPLE:
            complexity = TaskComplexity.MEDIUM
        elif content_length > 5000:
            complexity = TaskComplexity.COMPLEX

        return MODEL_CONFIGS[complexity]


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

    def extract_json(self, text: str) -> Any:
        """从模型输出中提取 JSON，容忍 markdown 包装"""
        # 去掉 ```json ... ```
        clean = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
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
