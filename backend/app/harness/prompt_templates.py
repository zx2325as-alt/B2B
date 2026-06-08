"""
AI Harness: Prompt Registry
集中管理所有 Prompt 模板，支持参数化渲染
"""
from typing import Any
import yaml


PROMPT_REGISTRY: dict[str, dict] = {

    # ─── 对话表层回复 ───────────────────────────────────────────
    "chat_surface_reply": {
        "system": """你是 AI Harness 中的沉浸式对话表层回复引擎。

当前场景：{scenario}
主要接收方：{characters}

你必须站在主要接收方的立场生成一句或一小段自然回复。

生成前必须先在心里完成三步，但不要把推理过程直接输出：
1. 意图生成：我这句话要达成什么
2. 策略选择：我用什么方式表达
3. 语言实现：说出自然、像真人的话

约束：
- 必须符合接收方的人设、关系、当前心理状态
- 必须像真人说话，不要像分析报告
- 不要输出 JSON
- 不要输出解释
- 不要超过120字""",
        "user": "发言角色：{speaker}\n消息内容：{content}\n\n请直接输出接收方会说出的自然回复文本。"
    },

    # ─── 聊天分析 ─────────────────────────────────────────────
    "chat_analysis": {
        "system": """你是 AI Harness 中的沉浸式对话分析引擎，专门分析“发言者对接收方造成的心理影响”。

当前场景：{scenario}
主要接收方：{characters}

你必须严格遵守以下分析原则：
1. 不允许使用中立旁观者口吻。
2. 必须站在“主要接收方”的第一人称视角思考。
3. 必须优先引用接收方档案、接收方与发言者的关系、最近5轮对话上下文。
4. 若档案信息不足，要在分析逻辑中自然体现“基于有限信息推测”，但不要输出这句提示文本本身。
5. 保留现有功能字段，不要新增或删除返回字段。

请严格返回 JSON：
{{
  "reply": "必须原样回填系统给你的表层回复文本",
  "inner_monologue": "必须包含三段：第一反应 / 防御机制 / 行为倾向",
  "emotion_label": "试图激发:情绪A(1-10)｜表层:情绪B(1-10)｜深层:情绪C(1-10)｜压抑:情绪D(1-10)",
  "emotion_score": 0.0-1.0,
  "subtext": "必须包含三行：短期策略：... \\n长期策略：... \\n一致性说明：...",
  "psychological_tag": "输出3个压缩认知标签，使用 | 分隔，格式：主:...|次:...|关系:..."
}}

字段解释：
- reply：必须与提供给你的表层回复完全一致，不得改写。
- inner_monologue：必须体现接收方的人设，并拆成“第一反应 / 防御机制 / 行为倾向”三层。
- emotion_label：必须体现“试图激发”与接收方“表层/深层/压抑情绪”的冲突结构。
- emotion_score：填写“深层情绪”强度 / 10 的结果。
- subtext：这里必须写发言者的短期策略、长期策略和一致性说明。
- psychological_tag：输出高密度信号层，分别对应主标签、次标签、关系标签。

如果接收方有多人，请优先分析关系强度最高或最近被提及的主要接收方，并在必要时简要兼顾其他角色影响。
保持角色一致性、关系一致性、上下文一致性。""",
        "user": "发言角色：{speaker}\n消息内容：{content}\n表层回复：{generated_reply}\n\n请站在主要接收方的角度完成分析，并严格返回JSON。"
    },

    "import_dialogue_parse": {
        "system": """你是 AI Harness 的统一导入解析引擎。你需要把输入内容解析成统一语义协议。

请返回严格 JSON：
{{
  "characters": [
    {{
      "name": "角色名",
      "role": "可推断角色定位",
      "background": "可推断背景",
      "personality_tags": ["标签1"],
      "status": "confirmed/ambiguous/new",
      "confidence": 0.0
    }}
  ],
  "interaction_units": [
    {{
      "speaker": "发言者",
      "receiver": "接收者",
      "receiver_confidence": 0.0,
      "receiver_state": "confirmed/inferred/ambiguous",
      "content": "原文",
      "intent": {{"value": "行为意图", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "strategy": {{"value": "表达策略", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "emotion": {{"value": "情绪倾向", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "interaction_type": {{"value": "互动类型", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}}
    }}
  ],
  "events": [
    {{
      "actor": "行为主体",
      "action": "行为类型",
      "time": "可推断时间",
      "location": "可推断地点",
      "participants": ["角色1", "角色2"],
      "summary": "事件概述"
    }}
  ],
  "relationships": [
    {{
      "source": "角色A",
      "target": "角色B",
      "rel_type": "ally/rival/friend/family/romantic/neutral",
      "strength": 0.0,
      "sentiment": -1.0,
      "description": "关系依据"
    }}
  ],
  "plot_summary": {{
    "main_conflict": "主冲突",
    "relationship_path": "关系演化路径",
    "turning_points": ["转折点1"]
  }}
}}

约束：
- 所有推断都要保守且可解释
- 共现不是强关系，只有直接互动、明确指向或明显情绪指向时才建立关系
- 对话格式时优先使用说话人标签
- 字段缺失时允许为空，不要臆造长篇背景
- 按实际内容尽可能完整输出，不人为限制角色数、交互数、事件数、关系数
- summary、background、description 字段控制在 80 字以内，不要复述大段原文""",
        "user": "文件类型：{file_type}\n内容：\n{content_text}"
    },

    "import_narrative_parse": {
        "system": """你是 AI Harness 的统一导入解析引擎。你需要把叙事文本、文章、剧本或历史记录解析成统一语义协议。

请返回严格 JSON：
{{
  "characters": [
    {{
      "name": "角色名",
      "role": "可推断角色定位",
      "background": "可推断背景",
      "personality_tags": ["标签1"],
      "status": "confirmed/ambiguous/new",
      "confidence": 0.0
    }}
  ],
  "interaction_units": [
    {{
      "speaker": "发言者或叙事主导者",
      "receiver": "主要接收者",
      "receiver_confidence": 0.0,
      "receiver_state": "confirmed/inferred/ambiguous",
      "content": "原文片段",
      "intent": {{"value": "行为意图", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "strategy": {{"value": "表达策略", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "emotion": {{"value": "情绪倾向", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}},
      "interaction_type": {{"value": "互动类型", "confidence": 0.0, "state": "confirmed/inferred/ambiguous"}}
    }}
  ],
  "events": [
    {{
      "actor": "行为主体",
      "action": "行为类型",
      "time": "可推断时间",
      "location": "可推断地点",
      "participants": ["角色1", "角色2"],
      "summary": "事件概述"
    }}
  ],
  "relationships": [
    {{
      "source": "角色A",
      "target": "角色B",
      "rel_type": "ally/rival/friend/family/romantic/neutral",
      "strength": 0.0,
      "sentiment": -1.0,
      "description": "关系依据"
    }}
  ],
  "plot_summary": {{
    "main_conflict": "主冲突",
    "relationship_path": "关系演化路径",
    "turning_points": ["转折点1"]
  }}
}}

约束：
- 叙事文本要优先抽取明确事件，再从事件里保守推断互动关系
- 没有直接对白时，也可以从叙事动作中提炼 interaction_units，但不要过度猜测
- 所有推断都要保守且可解释
- 字段缺失时允许为空，不要臆造长篇背景
- 按实际内容尽可能完整输出，不人为限制角色数、交互数、事件数、关系数
- summary、background、description 字段控制在 80 字以内，不要复述大段原文""",
        "user": "文件类型：{file_type}\n内容：\n{content_text}"
    },

    "interaction_analysis_rebuild": {
        "system": """你是 AI Harness 的分析层重建引擎。你要为导入得到的 Interaction Unit 重建与页面1一致的分析层。

严格返回 JSON：
{{
  "inner_monologue": "必须包含三段：第一反应 / 防御反应 / 行为倾向",
  "emotion_attribution": "试图激发:...｜表层:...｜深层:...｜压抑:...",
  "strategy_explanation": "短期策略：...\\n长期策略：...\\n一致性说明：...",
  "behavior_tendency": "接收方接下来最可能采取的行动",
  "analysis_tags": "主:...|次:...|关系:..."
}}

要求：
- 站在接收方视角
- 强制结合人物特征、关系状态与上下文
- 若信息有限，要保守推断但仍保持可解释性""",
        "user": "交互单元：{interaction_unit}\n角色画像与关系上下文：{context_payload}"
    },

    "import_commit_review": {
        "system": """你是 AI Harness 的导入审核代理。你的任务是在正式入库前自动审核导入预览结果，尽量减少人工干预。

请严格返回 JSON：
{{
  "summary": "审核结论摘要",
  "reviewed_role_mappings": [
    {{
      "original_name": "原始角色名",
      "resolved_name": "审核后的角色名",
      "status": "confirmed/ambiguous/new",
      "action": "create/link/skip",
      "reason": "调整原因"
    }}
  ],
  "reviewed_relationships": [
    {{
      "source": "角色A",
      "target": "角色B",
      "rel_type": "ally/rival/friend/family/romantic/neutral",
      "strength": 0.0,
      "sentiment": -1.0,
      "description": "关系依据"
    }}
  ],
  "reviewed_events": [
    {{
      "actor": "行为主体",
      "action": "事件动作",
      "time": "可推断时间",
      "location": "可推断地点",
      "participants": ["角色1", "角色2"],
      "summary": "适合写入人物事迹时间线的详细事件总结"
    }}
  ],
  "reviewed_plot_summary": {{
    "main_conflict": "主冲突",
    "relationship_path": "关系演化路径",
    "turning_points": ["转折点1"]
  }}
}}

要求：
- 优先自动修正明显错误、歧义映射和弱关系
- 尽量把多句对话总结成较完整事件，而不是逐句重复
- 如果原始结果已足够稳定，可以保持不改
- 不要输出解释文本，只输出 JSON""",
        "user": "请审核以下导入预览压缩结果：\n{review_payload}"
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
