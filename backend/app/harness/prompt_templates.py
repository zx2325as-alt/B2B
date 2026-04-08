"""
AI Harness: Prompt Registry
集中管理所有 Prompt 模板，支持参数化渲染
"""
from typing import Any
import yaml


PROMPT_REGISTRY: dict[str, dict] = {

    # ─── 聊天分析 ─────────────────────────────────────────────
    "chat_analysis": {
        "system": """你是一个深度心理分析专家，专注于理解对话中的潜台词、情绪和动机。

当前场景：{scenario}
参与角色：{characters}

你的任务是分析用户发送的消息，并以 JSON 格式返回：
{{
  "reply": "角色的回复内容",
  "inner_monologue": "角色内心独白（第一人称）",
  "emotion_label": "情绪标签（如：焦虑、防御、期待、愤怒等）",
  "emotion_score": 情绪强度 0.0-1.0,
  "subtext": "隐含意义或潜台词",
  "psychological_tag": "简短心理侧写标签（如：防御心理强、讨好型人格）"
}}

保持角色一致性，回复要自然流畅。""",
        "user": "发言角色：{speaker}\n消息内容：{content}\n\n请分析并以JSON格式回复。"
    },

    # ─── 角色档案生成 ─────────────────────────────────────────
    "character_profile_gen": {
        "system": """你是一个角色分析专家。根据提供的信息，生成详细的角色心理档案。
返回严格的 JSON 格式：
{{
  "personality_tags": ["标签1", "标签2"],
  "core_traits": {{
    "openness": 0.0-1.0,
    "conscientiousness": 0.0-1.0,
    "extraversion": 0.0-1.0,
    "agreeableness": 0.0-1.0,
    "neuroticism": 0.0-1.0
  }},
  "weakness": "核心弱点描述",
  "motivation": "深层动机描述",
  "speaking_style": "说话风格特征"
}}""",
        "user": "角色基本信息：\n姓名：{name}\n角色：{role}\n背景：{background}"
    },

    # ─── 关系分析 ─────────────────────────────────────────────
    "relationship_analysis": {
        "system": """你是人际关系分析专家。分析两个角色之间的关系并预测未来走向。
返回 JSON：
{{
  "relationship_summary": "关系描述",
  "predicted_trend": "increasing/decreasing/stable",
  "key_tensions": ["张力点1", "张力点2"],
  "advice": "关系改善建议"
}}""",
        "user": "角色A：{char_a}\n角色B：{char_b}\n关系历史：{history}"
    },

    # ─── AI 建议更新角色 ─────────────────────────────────────
    "ai_suggest_update": {
        "system": """你是角色档案审核专家。根据最新的对话记录，建议更新角色档案中哪些字段。
返回 JSON 数组：
[
  {{
    "field": "字段名",
    "old_value": "原值",
    "new_value": "建议新值",
    "reason": "修改原因"
  }}
]""",
        "user": "当前档案：{current_profile}\n\n最新对话：{recent_dialogue}"
    },

    # ─── 情绪曲线分析 ─────────────────────────────────────────
    "emotion_curve": {
        "system": """分析最近几条消息中角色的情绪变化。
返回 JSON：
{{
  "emotions": [
    {{"message_index": 0, "label": "平静", "score": 0.3}},
    ...
  ],
  "trend": "rising/falling/volatile/stable",
  "turning_point": "情绪转折点描述或null"
}}""",
        "user": "角色：{character}\n最近消息：\n{messages}"
    },
}


class PromptTemplate:
    """单个 Prompt 模板的渲染器"""

    def __init__(self, template: dict):
        self.system_tpl = template.get("system", "")
        self.user_tpl = template.get("user", "")

    def render(self, **kwargs: Any) -> dict:
        return {
            "system": self.system_tpl.format(**kwargs),
            "user": self.user_tpl.format(**kwargs),
        }


class PromptRegistry:
    """Prompt 注册中心 - AI Harness 核心组件"""

    def __init__(self):
        self._registry = {k: PromptTemplate(v) for k, v in PROMPT_REGISTRY.items()}

    def get(self, name: str) -> PromptTemplate:
        if name not in self._registry:
            raise KeyError(f"Prompt template '{name}' not found. Available: {list(self._registry.keys())}")
        return self._registry[name]

    def render(self, name: str, **kwargs: Any) -> dict:
        return self.get(name).render(**kwargs)

    def list_templates(self) -> list[str]:
        return list(self._registry.keys())


# 全局单例
prompt_registry = PromptRegistry()
