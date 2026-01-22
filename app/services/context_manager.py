import re
import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.sql_models import ConversationSession, Relationship, DialogueLog, Scenario
from app.services.character_service import character_service
from app.services.scenario_service import scenario_service
from app.services.knowledge import knowledge_service
from app.core.config import settings
from app.utils.logger import logger

from app.services.character_profile_formatter import character_formatter

class ContextManager:
    """
    对话上下文管理器 (Dialogue Context Manager)
    
    核心职责:
    1. 状态管理 (Session State): 维护当前会话的流转状态。
    2. 上下文聚合 (Context Aggregation): 从多个来源(角色、场景、历史、知识库)收集信息。
    3. 实体识别 (Entity Extraction): 识别输入中的关键实体(如提到的角色)。
    4. 提示词组装 (Prompt Assembly): 为LLM构建最终的系统提示词和上下文。
    """

    def parse_speaker_and_content(self, input_text: str) -> tuple[str, str]:
        """
        解析标准输入格式 "【Speaker】说：Content"
        
        Args:
            input_text (str): 原始输入文本
            
        Returns:
            tuple[str, str]: (说话人姓名, 实际说话内容)。如果未匹配，返回 (None, 原始文本)
        """
        match = re.match(r"^【(.*?)】说：(.*)$", input_text, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, input_text

    async def build_composite_context(
        self, 
        db: Session, 
        session: ConversationSession, 
        user_input: str,
        nlu_result: Any = None
    ) -> Dict[str, Any]:
        """
        构建复合上下文，供DialogueService使用。
        此方法实现了“对话舞台”模型 (Dialogue Stage Model)，确保LLM能够感知当前场景下的所有活跃角色和动态。
        
        Args:
            db (Session): 数据库会话
            session (ConversationSession): 当前对话会话对象
            user_input (str): 用户输入
            nlu_result (Any): NLU分析结果(可选)
            
        Returns:
            Dict[str, Any]: 包含上下文文档、场景、角色、活跃角色列表、RAG文档、系统提示词等信息的字典。
        """
        
        # 0. 解析当前发言者 (Parse Current Speaker)
        # 从输入中提取显式的说话人信息，用于后续的角色识别和舞台构建
        speaker_name, actual_content = self.parse_speaker_and_content(user_input)
        
        # 1. 确定当前场景 (Scenario)
        # 如果会话绑定了特定场景，加载该场景的配置（如系统提示词模板、处理步骤）
        current_scenario = None
        if session.scenario_id:
            current_scenario = scenario_service.get_scenario(db, session.scenario_id)
        
        # 2. 识别相关人物 (Characters) - 舞台角色识别
        # 这一步旨在找出当前语境下所有相关的角色，包括：
        # (A) 用户显式选中的对话对象
        # (B) 当前正在说话的角色 (如果是角色扮演模式)
        # (C) 文本中提到的其他角色 (被动提及)
        all_chars = character_service.get_characters(db, limit=1000)
        mentioned_chars = []
        
        # (A) 显式选中的角色 (Frontend selection)
        selected_char = None
        if session.character_id:
            selected_char = character_service.get_character(db, session.character_id)
            if selected_char:
                mentioned_chars.append(selected_char)

        # (B) 识别说话者角色对象 (Identify Speaker Character Object)
        current_speaker_char = None
        if speaker_name:
            # 根据名字查找角色对象
            for c in all_chars:
                if c.name == speaker_name:
                    current_speaker_char = c
                    # 如果尚未添加，则加入提及列表
                    if not any(mc.id == c.id for mc in mentioned_chars):
                        mentioned_chars.append(c)
                    break
        
        # (C) 动态提取提及的角色 (Dynamically extracted characters from text)
        # 简单的关键词匹配：如果名字出现在文本中，认为该角色在场或被提及
        # 例如: "飞飞飞" in "飞飞飞是谁" -> True
        for c in all_chars:
            if any(mc.id == c.id for mc in mentioned_chars):
                continue
            if (c.name and c.name.strip() and c.name in actual_content) or re.search(rf"\b{c.id}\b", actual_content):
                mentioned_chars.append(c)
                logger.info(f"ContextManager: Detected character '{c.name}' (ID: {c.id}) in user input.")

        # 3. 构建“对话舞台”状态 (Build Dialogue Stage State)
        # 这一步是为了让LLM理解“刚才发生了什么”以及“谁在场”。
        # 尤其是在多人对话场景中，这对于保持对话连贯性至关重要。
        recent_active_names = set()
        last_round_info = "无上一轮对话"
        
        if session.id and session.id != "ephemeral":
            # 获取最近的对话日志，用于分析活跃角色
            # 增加limit以确保能捕捉到较早之前的参与者
            recent_logs = db.query(DialogueLog).filter(
                DialogueLog.session_id == session.id
            ).order_by(DialogueLog.created_at.desc()).limit(30).all()
            
            if recent_logs:
                # 提取上一轮对话信息，用于构建 prompt 中的 context
                last_log = recent_logs[0]
                # 尝试解析上一轮的说话人
                last_speaker, last_content = self.parse_speaker_and_content(last_log.user_input)
                if not last_speaker: last_speaker = "用户"
                
                # 记录上一轮交互概要
                last_round_info = f"{last_speaker} 说：{last_content}"

                # 提取最近活跃的角色名单
                for log in recent_logs:
                    s_name, _ = self.parse_speaker_and_content(log.user_input)
                    if s_name: recent_active_names.add(s_name)
        
        # 将当前说话人和提及的人也加入活跃名单
        if speaker_name: recent_active_names.add(speaker_name)
        for mc in mentioned_chars: recent_active_names.add(mc.name)
        
        # 封装舞台上下文数据
        stage_context = {
            "recent_characters": list(recent_active_names),
            "last_round": last_round_info,
            "current_input": f"{speaker_name}说：{actual_content}" if speaker_name else user_input,
            "speaker_name": speaker_name or "用户",
            "speaker_char": current_speaker_char
        }

        # 4. 动态组装最终的系统提示词 (System Prompt Construction)
        # 全景分析模式：
        # 这里的策略是：如果存在场景配置，使用场景的基础 System Role；
        # 否则使用默认逻辑。这里主要处理 System Role 的基础部分。
        customized_system_role = None
        
        if current_scenario:
            base_system_role = current_scenario.system_role or ""
            # 在全景模式下，system_role 通常是通用的分析师指令，但也可能包含占位符
            final_system_role = base_system_role
            customized_system_role = final_system_role

        # 5. 构建详细上下文组件 (Context Components)
        # 准备注入到 Prompt 中的具体文本块
        analysis_context = []
        char_info_context = []
        rel_context = []
        
        # (A) 角色档案上下文 (Character Context)
        # 为所有相关角色生成详细的档案描述
        for char in mentioned_chars:
            # 基础信息
            char_info = f"【角色档案 (ID:{char.id})】\n姓名: {char.name}\n性格: {char.attributes.get('personality', '未知')}\n特征: {char.traits}"
            
            # 动态画像 (Dynamic Profile): 包含随时间变化的属性
            if hasattr(char, "dynamic_profile") and char.dynamic_profile:
                char_info += f"\n动态画像: {json.dumps(char.dynamic_profile, ensure_ascii=False)}"
            
            char_info_context.append(char_info)
            
            # 关系网络 (Relationships): 该角色与其他角色的关系
            rels = character_service.get_relationships(db, char.id)
            if rels:
                rel_strs = []
                for r in rels:
                    target_id = r.target_id if r.source_id == char.id else r.source_id
                    target = character_service.get_character(db, target_id)
                    target_name = target.name if target else "Unknown"
                    rel_strs.append(f"- 与 {target_name}: {r.relation_type} ({r.details})")
                rel_context.append(f"【{char.name} 的社会关系】\n" + "\n".join(rel_strs))

        # (B) RAG 知识检索 (Knowledge Retrieval)
        # 基于实际对话内容检索相关文档
        rag_docs = await knowledge_service.retrieve(actual_content)

        # 6. 组装最终上下文列表 (Assemble Final Context List)
        final_context_list = []
        final_context_list.extend(char_info_context)
        final_context_list.extend(rel_context)
        final_context_list.extend(rag_docs)

        return {
            "context_docs": final_context_list, # 用于注入 Prompt 的文本文档列表
            "scenario": current_scenario,       # 当前场景对象
            "character": selected_char,         # 用户选中的主要交互角色
            "mentioned_chars": mentioned_chars, # 所有提及/活跃的角色对象列表
            "rag_docs": rag_docs,               # 检索到的知识片段
            "customized_system_role": customized_system_role, # 定制后的 System Role
            "stage_context": stage_context      # 舞台状态数据
        }

context_manager = ContextManager()
