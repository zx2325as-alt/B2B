from app.models.schemas import NLUOutput
from app.services.llm import llm_service
from app.utils.logger import logger
from app.core.config import settings
import json

class DialogueService:
    """
    对话生成服务 (Dialogue Generation Service)
    
    核心职责:
    1. 提示词工程 (Prompt Engineering): 组装 System Prompt 和 User Input。
    2. LLM 调用 (LLM Invocation): 调用底层 LLM 服务获取回复。
    3. 异常处理 (Error Handling): 处理 LLM 连接失败或格式错误。
    """

    async def generate_response(
        self, 
        user_input: str, 
        nlu_result: NLUOutput, 
        context_docs: list, 
        user_profile: dict,
        scenario = None,
        character = None,
        customized_system_role: str = None,
        stage_context: dict = None
    ) -> str:
        """
        生成对话回复的核心方法。
        
        Args:
            user_input (str): 用户的原始输入。
            nlu_result (NLUOutput): 意图识别和情感分析结果。
            context_docs (list): 上下文文档列表（包含角色、关系、知识库内容）。
            user_profile (dict): 用户画像信息。
            scenario (Scenario, optional): 当前场景对象。
            character (Character, optional): 当前主要对话角色（可选）。
            customized_system_role (str, optional): 定制的系统角色设定（通常来自 ContextManager）。
            stage_context (dict, optional): 舞台上下文信息（包含活跃角色、上一轮对话等）。
            
        Returns:
            str: LLM 生成的原始 JSON 字符串。
        """
        
        # 1. 准备上下文片段 (Prepare Context Parts)
        history_summary = "暂无历史摘要" # 占位符，未来可接入摘要服务
        
        # 确定核心名称
        char_name = character.name if character else "用户"
        scenario_name = scenario.name if scenario else "深度对话理解中枢"
        
        # 拼接上下文文档
        # RAG Semantic Retrieval
        try:
            # Construct filters
            rag_filters = {}
            if character:
                 rag_filters["character_id"] = str(character.id)
            
            # Use settings for top_k
            top_k = getattr(settings, "RAG_SIMILARITY_TOP_K", 3)
            
            # Use Hybrid Retrieval (BM25 + Semantic)
            rag_results = await knowledge_service.retrieve_hybrid(user_input, top_k=top_k, filters=rag_filters if rag_filters else None)
            
            if rag_results:
                rag_context = []
                for item in rag_results:
                    content = item.get("content", "")
                    meta = item.get("metadata", {})
                    timestamp = meta.get("timestamp", "")
                    # Add timestamp to context if available
                    prefix = f"[{timestamp}] " if timestamp else ""
                    rag_context.append(f"[相关历史记忆]: {prefix}{content}")
                
                context_docs.extend(rag_context)
                logger.info(f"DialogueService: Retrieved {len(rag_results)} RAG documents.")
        except Exception as e:
            logger.warning(f"DialogueService: RAG retrieval failed: {e}")

        context_str = "\n".join(context_docs)
        
        # 格式化 NLU 信息
        nlu_info = (
            f"意图: {nlu_result.intent}\n"
            f"情感: {nlu_result.emotion}\n"
            f"隐含暗示: {nlu_result.implicit_hint or '无'}"
        )

        # 2. 构建系统提示词 (Construct System Prompt)
        # 优先级: 场景配置的 Prompt Template > 硬编码的默认逻辑
        
        system_prompt = ""
        used_template = False
        
        if scenario and scenario.prompt_template:
            try:
                # 准备模板变量
                recent_chars_str = "无"
                last_round_str = "无"
                current_input_str = user_input
                
                if stage_context:
                    rc = stage_context.get("recent_characters", [])
                    if rc: recent_chars_str = ", ".join(rc)
                    last_round_str = stage_context.get("last_round", "无")
                    current_input_str = stage_context.get("current_input", user_input)

                format_context = {
                    "system_role": customized_system_role or scenario.system_role,
                    "processing_steps": json.dumps(scenario.processing_steps, ensure_ascii=False) if scenario.processing_steps else "",
                    "user_role": user_profile.get('role', 'user'),
                    "context_docs": context_str,
                    "history_summary": history_summary,
                    "user_input": user_input, # 原始输入
                    "current_input": current_input_str, # 格式化后的输入 (带 Speaker)
                    "recent_characters": recent_chars_str,
                    "last_round": last_round_str,
                    "nlu_info": nlu_info,
                    # 兼容性字段 (防止旧模板报错)
                    "user_status": "active",
                    "user_cognitive_level": "Standard",
                    "user_info_preference": "Balanced",
                    "conversation_style_history": "Neutral"
                }
                
                # 安全格式化模板
                system_prompt = scenario.prompt_template.format(**format_context)
                used_template = True
                logger.info("DialogueService: Used Scenario Prompt Template.")
                
            except Exception as e:
                logger.warning(f"Template formatting failed: {e}. Falling back to default logic.")
                used_template = False

        if not used_template:
            # 降级方案：硬编码逻辑 (Legacy or Backup)
            # Load config
            config = settings.PROMPTS.get("dialogue", {})
            fallback_template = config.get("fallback_prompt", "")
            
            # 基础 System Role
            if customized_system_role:
                 system_role = customized_system_role
            else:
                 # 统一使用配置中的角色设定，不再拼接 role_prefix/suffix
                 # 如果 scenario 有 system_role，优先使用，否则使用默认的顾问角色
                 default_role = config.get("default_system_role", "你是一位战略顾问，协助用户分析局势。")
                 system_role = scenario.system_role if (scenario and scenario.system_role) else default_role
            
            # 组装完整 Prompt
            # 如果配置中有 fallback_prompt，则使用它；否则使用简单的默认格式
            if fallback_template:
                system_prompt = fallback_template.format(
                    system_role=system_role,
                    context_str=context_str,
                    nlu_info=nlu_info
                )
            else:
                system_prompt = f"{system_role}\n\n上下文：{context_str}\n\n意图：{nlu_info}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        # 3. 调用 LLM (Call LLM)
        # 强制要求 JSON 格式输出，便于后续解析
        response_format = {"type": "json_object"}
        
        temperature = settings.PROMPTS.get("dialogue", {}).get("temperature", 0.7)

        response = await llm_service.chat_completion(
            messages, 
            temperature=temperature,
            response_format=response_format
        )
        
        if not response:
            error_msgs = settings.PROMPTS.get("system_messages", {}).get("errors", {}).get("llm_connection_failed", {})
            return json.dumps({
                "analysis": error_msgs.get("analysis", "连接失败"),
                "final_translation": error_msgs.get("final_translation", "抱歉，我现在无法连接到智能大脑。(LLM Connection Error)")
            }, ensure_ascii=False)

        return response

dialogue_service = DialogueService()
