from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class DialogueInput(BaseModel):
    text: str = Field(..., description="用户当前输入的文本")
    history: List[Dict[str, str]] = Field(default=[], description="对话历史记录 (List of {role, content})")
    user_id: str = Field(default="guest", description="用户唯一标识符")
    session_id: Optional[str] = Field(None, description="会话ID")
    scenario_id: Optional[int] = Field(None, description="强制指定的场景ID")
    character_id: Optional[int] = Field(None, description="指定的对话角色ID")
    character_name: Optional[str] = Field(None, description="角色名称(用于上下文辅助)")

class NLUOutput(BaseModel):
    intent: str = Field(..., description="用户的主要意图")
    sub_intent: Optional[str] = Field(None, description="更具体的子意图")
    emotion: str = Field(..., description="检测到的情感状态")
    psychological_state: Optional[str] = Field(None, description="潜在心理状态 (如：讽刺、犹豫)")
    slots: Dict[str, Any] = Field(default={}, description="提取的实体与关键参数")
    implicit_hint: Optional[str] = Field(None, description="隐含意图或潜台词")
    need_clarification: bool = Field(default=False, description="系统是否需要进一步澄清")
    clarification_question: Optional[str] = Field(None, description="澄清问题的内容")
    reasoning: str = Field(..., description="做出上述判断的推理依据")

class GenerationOutput(BaseModel):
    content: str = Field(..., description="生成的回复内容")
    format_type: str = Field(..., description="回复的格式类型 (text/json/markdown)")
    references: List[str] = Field(default=[], description="参考的文档或知识来源")

class CharacterFeedbackInput(BaseModel):
    session_id: str = Field(..., description="相关的会话ID")
    log_id: Optional[int] = Field(None, description="关联的对话日志ID")
    is_accurate: bool = Field(..., description="角色画像是否准确")
    reason_category: Optional[str] = Field(None, description="不准确的原因分类")
    comment: Optional[str] = Field(None, description="具体反馈评论")
    context_data: Optional[Dict[str, Any]] = Field(None, description="对话上下文与分析依据快照")
