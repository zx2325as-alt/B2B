"""
API 端点定义 (API Endpoints)

本模块定义了系统的核心 API 接口，负责处理前端请求、调用后端服务并返回结果。
主要包含以下功能模块：
1. 会话管理 (Session Management): 创建、更新、查询会话状态。
2. 对话处理 (Chat Processing): 核心对话接口，支持流式响应 (Streaming)。
3. 角色管理 (Character Management): 角色档案的同步与总结。
4. 反馈系统 (Feedback System): 用户对对话质量的打分与反馈。
5. 日志查询 (Log Querying): 获取历史对话记录。
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.core.database import get_db
from app.models.schemas import DialogueInput, NLUOutput, CharacterFeedbackInput
from app.models.sql_models import DialogueLog, Relationship, Scenario, ConversationSession, CharacterFeedback, CharacterVersion, AnalysisLog
from app.core.engine import nlu_engine
from app.services.knowledge import knowledge_service
from app.services.user_profile import user_service
from app.services.dialogue import dialogue_service
from app.services.extraction_service import extraction_service
from app.services.scenario_service import scenario_service
from app.services.character_service import character_service
from app.services.context_manager import context_manager
from app.models.domain_schemas import CharacterUpdate
from app.utils.logger import logger
import json
import time
import asyncio
import re

router = APIRouter()

from app.core.config import settings

@router.post("/sessions", summary="创建会话")
def create_session(
    user_id: str,
    character_id: Optional[int] = None,
    scenario_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    创建一个新的会话上下文 (Create Session).
    
    Args:
        user_id (str): 用户唯一标识
        character_id (int, optional): 初始绑定的角色ID
        scenario_id (int, optional): 初始绑定的场景ID
        db (Session): 数据库会话
        
    Returns:
        dict: { "session_id": str, "status": "created" }
    """
    import uuid
    # Create new session
    session_id = str(uuid.uuid4())
    new_session = ConversationSession(
        id=session_id,
        user_id=user_id,
        character_id=character_id,
        scenario_id=scenario_id,
        is_active=1
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {"session_id": session_id, "status": "created"}

@router.put("/sessions/{session_id}", summary="更新会话信息")
def update_session(
    session_id: str,
    character_id: Optional[int] = None,
    scenario_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    更新现有会话的状态 (Update Session).
    通常用于用户在界面上切换当前互动的角色或场景。
    
    Args:
        session_id (str): 会话ID
        character_id (int, optional): 新的角色ID
        scenario_id (int, optional): 新的场景ID
        
    Returns:
        dict: 更新后的状态信息
    """
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if character_id is not None:
        session.character_id = character_id
        # Also update user_selected_character_id if you have that column, 
        # but based on models, it seems we use character_id.
        # User mentioned "user_selected_character_id" in their prompt, let's check sql_models.
        # If sql_models only has character_id, we use that.
        
    if scenario_id is not None:
        session.scenario_id = scenario_id
        
    session.updated_at = func.now()
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": "updated", "character_id": session.character_id}

@router.get("/sessions/{session_id}", summary="获取会话信息")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """
    获取会话详情 (Get Session Details).
    """
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.post("/chat", summary="智能对话接口", description="流式返回：先返回NLU分析JSON，再返回生成内容")
async def chat(
    input_data: DialogueInput, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    核心对话接口 (Core Chat Endpoint).
    采用流式响应 (Streaming Response) 模式，分阶段返回数据，以提供低延迟的用户体验。
    
    Args:
        input_data (DialogueInput): 用户输入数据(文本、会话ID等)
        background_tasks (BackgroundTasks): 后台任务队列 (用于异步日志记录等)
        db (Session): 数据库会话
        
    Flow:
        1. **Session Sync (会话同步)**: 确保请求上下文与数据库会话状态一致，处理角色/场景绑定。
        2. **NLU Analysis (意图识别)**: 调用 `nlu_engine` 分析用户意图(Intent)、情感倾向和是否需要追问。
        3. **Context Build (上下文构建)**: 调用 `context_manager` 聚合所有相关上下文(角色档案、知识库片段、短期记忆)。
        4. **Generation (回复生成)**: 调用 `dialogue_service` 生成回复，支持思维链 (Thinking Process)。
        5. **Streaming (流式输出)**: 
            - Chunk 1: NLU分析结果 (JSON) - 让前端知道系统理解了什么。
            - Chunk 2: 思考过程/意图分析 (Text/JSON) - 展示 AI 的思考路径。
            - Chunk 3: 最终回复 (Text) - 实际的角色回复。
            - Chunk 4: 元数据(Log ID) (JSON) - 用于后续的反馈打分。
            
    Returns:
        StreamingResponse: application/x-ndjson (Newline Delimited JSON) 格式的流式数据。
    """
    start_time = time.time()
    
    # --- 0. Session Handling (会话与上下文同步) ---
    session_obj = None
    if input_data.session_id:
        session_obj = db.query(ConversationSession).filter(ConversationSession.id == input_data.session_id).first()
        if session_obj:
            session_obj.updated_at = func.now()
            # 如果输入数据中缺少 character_id/scenario_id，则从 Session 中回填
            if not input_data.character_id and session_obj.character_id:
                input_data.character_id = session_obj.character_id
            if not input_data.scenario_id and session_obj.scenario_id:
                input_data.scenario_id = session_obj.scenario_id
            db.commit()
    
    # 预取角色名称，辅助 NLU 分析
    if input_data.character_id:
        char_obj = character_service.get_character(db, input_data.character_id)
        if char_obj:
            input_data.character_name = char_obj.name

    # --- 1. NLU Analysis (快速意图分析) ---
    logger.info(f"正在分析输入: {input_data.text} (Character: {input_data.character_name})")
    nlu_result = await nlu_engine.analyze(input_data)
    
    # 追问机制 (Clarification): 如果 NLU 认为需要追问，直接返回追问问题，中断后续流程
    if nlu_result.need_clarification:
        return {
            "response": nlu_result.clarification_question,
            "nlu_analysis": nlu_result.dict(),
            "type": "clarification"
        }

    # --- 2. Context Management (上下文构建) ---
    # 构建包含角色档案、知识库、场景信息的复合上下文
    
    # 如果没有 session_obj (例如新会话未持久化)，创建一个临时的 session 对象传递给 Context Manager
    if not session_obj:
        session_obj = ConversationSession(
            id=input_data.session_id or "ephemeral",
            user_id=input_data.user_id,
            character_id=input_data.character_id,
            scenario_id=input_data.scenario_id
        )

    ctx_data = await context_manager.build_composite_context(
        db, session_obj, input_data.text, nlu_result
    )
    
    current_scenario = ctx_data['scenario']
    current_character = ctx_data['character']
    context_docs = ctx_data['context_docs']
    mentioned_chars = ctx_data['mentioned_chars']
    customized_system_role = ctx_data.get('customized_system_role')
    
    # Force Local Scenario Override (Development Feature - 仅用于开发调试)
    # local_scenario_path = r"e:\python\conda\PyTorch01\BtB\scenarios\hr_assistant.yaml"
    # local_scenario = load_local_scenario(local_scenario_path)
    # if local_scenario:
    #      current_scenario = local_scenario
    #      logger.info(f"Using local scenario override: {local_scenario.name}")

    # --- 3. Intent Routing (意图路由 - 可选) ---
    # 可以在此处理系统指令 (System Ops)，目前主要由 NLU 结果驱动
    system_intent = nlu_result.intent == "system_op"
    sub_intent = nlu_result.sub_intent
    
    # --- 4. User Profile (用户画像) ---
    profile = user_service.get_profile(input_data.user_id)
    
    # --- 5. Async Generator for Streaming Response (流式生成器) ---
    async def response_generator():
        # Step A: 立即返回 NLU 分析结果 (Yield Analysis Data First)
        # 这样前端可以立即展示 "AI 正在理解..." 的状态
        analysis_data = {
            "nlu_analysis": nlu_result.dict(),
            "scenario": current_scenario.name if current_scenario else None,
            "context_used": context_docs,
            "type": "streaming",
            "session_id": input_data.session_id
        }
        yield json.dumps(analysis_data, ensure_ascii=False) + "\n"
        
        # Step B: 调用生成服务 (Call Generation Service)
        # 这是一个耗时操作，通常需要几秒钟
        final_response_text = ""
        reasoning_content = None
        parsed_resp = None
        
        try:
            raw_response = await dialogue_service.generate_response(
                input_data.text,
                nlu_result,
                context_docs,
                profile,
                scenario=current_scenario,
                character=current_character,
                customized_system_role=customized_system_role,
                stage_context=ctx_data.get("stage_context")
            )
            
            # Step C: 解析响应 (Parse Response)
            # LLM 返回的通常是 JSON 字符串，包含 thinking_process 和 response
            final_response_text = raw_response
            try:
                parsed_resp = json.loads(raw_response)
                if isinstance(parsed_resp, dict):
                    # 1. 优先使用 Thinking Process 作为主要回复 (Use Thinking Process as Main Response)
                    thinking_process = parsed_resp.get("thinking_process")
                    
                    if thinking_process:
                        final_response_text = thinking_process
                    else:
                        # Fallback: 如果没有 thinking_process，尝试构建一个分析摘要
                        pa = parsed_resp.get("primary_analysis", {})
                        if pa and isinstance(pa, dict) and pa.get("intent_analysis"):
                            speaker = pa.get("speaker", "未知")
                            intent = pa.get("intent_analysis", "分析中...")
                            final_response_text = f"**【{speaker}】意图分析**\n{intent}"
                        elif parsed_resp.get("response"):
                            final_response_text = parsed_resp.get("response")
                        elif parsed_resp.get("content"):
                             final_response_text = parsed_resp.get("content")
                        else:
                             # If we really can't find a standard field, just try to show something useful
                             # or if it is empty, keep it empty string (handled later?)
                             final_response_text = str(parsed_resp) if parsed_resp else "（无有效回复内容）"
                    
                    # 2. 提取推理内容 (Extract Reasoning)
                    # 用于前端的 "Details" 展开栏或结构化展示
                    if parsed_resp.get("primary_analysis"):
                        reasoning_content = parsed_resp
                    else:
                        reasoning_content = (
                            parsed_resp.get("analysis") or 
                            parsed_resp.get("thought_process") or 
                            parsed_resp.get("reasoning")
                        )
            except:
                # 解析失败，说明返回的可能是纯文本
                pass

            # Step D: 返回最终结果 (Yield Final Response)
            result_data = {
                "response": final_response_text,
                "reasoning": reasoning_content
            }
            yield json.dumps(result_data, ensure_ascii=False) + "\n"
        
        except Exception as e:
            logger.error(f"Error during response generation: {e}")
            error_data = {
                "response": "系统处理请求时发生错误，请稍后重试。",
                "error": str(e)
            }
            yield json.dumps(error_data, ensure_ascii=False) + "\n"
            return

        # Step E: 后台任务与日志记录 (Background Logging)
        try:
            from app.core.database import SessionLocal
            with SessionLocal() as log_db:
                latency = (time.time() - start_time) * 1000
                log_entry = DialogueLog(
                    session_id=input_data.session_id or "unknown",
                    user_id=input_data.user_id,
                    user_input=input_data.text,
                    scenario_id=current_scenario.id if current_scenario and current_scenario.id != 9999 else None,
                    character_id=current_character.id if current_character else None,
                    bot_response=final_response_text,
                    nlu_result=nlu_result.dict(),
                    reasoning_content=json.dumps(reasoning_content, ensure_ascii=False) if reasoning_content else None,
                    latency_ms=latency
                )
                log_db.add(log_entry)
                log_db.commit()
                log_db.refresh(log_entry)
                
                # Yield Log ID for Frontend Feedback (返回 Log ID 供前端反馈使用)
                yield json.dumps({"type": "meta", "log_id": log_entry.id}, ensure_ascii=False) + "\n"
                
                # --- Active Collection & Relationship Updates (主动信息收集与关系更新) ---
                if parsed_resp:
                    try:
                        await extraction_service.process_analysis_results(
                            log_db, 
                            input_data.session_id, 
                            parsed_resp
                        )
                    except Exception as e:
                        logger.error(f"Side-effect processing failed: {e}")

        except Exception as e:
            logger.error(f"Logging failed: {e}")
            
    return StreamingResponse(response_generator(), media_type="application/x-ndjson")

@router.post("/chat/{log_id}/rate", summary="评价对话质量")
async def rate_dialogue(
    log_id: int, 
    rating: int, 
    feedback: str = None,
    db: Session = Depends(get_db)
):
    """
    提交用户反馈 (Submit User Feedback).
    
    Args:
        log_id (int): 对话日志ID (由/chat接口返回)
        rating (int): 评分 (1-5, 1=减少, 5=增加)
        feedback (str, optional): 文本反馈建议
        
    Logic:
        - 更新 `DialogueLog` 表中的评分和反馈。
        - 如果评分 <= 2，标记为 `is_archived_for_tuning`，用于后续优化模型。
    """
    log_entry = db.query(DialogueLog).filter(DialogueLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Log not found")
    
    log_entry.rating = rating
    if feedback:
        log_entry.feedback_text = feedback
        
    if rating <= 2:
        log_entry.is_archived_for_tuning = 1
        
    db.commit()
    return {"status": "success", "log_id": log_id}

@router.get("/logs", summary="获取对话日志")
async def get_logs(
    skip: int = 0, 
    limit: int = 50,
    min_rating: int = None,
    scenario_id: Optional[int] = None,
    character_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    查询历史对话日志 (Query Dialogue Logs).
    """
    query = db.query(DialogueLog)
    if min_rating is not None:
        query = query.filter(DialogueLog.rating >= min_rating)
    if scenario_id:
        query = query.filter(DialogueLog.scenario_id == scenario_id)
    if character_id:
        query = query.filter(DialogueLog.character_id == character_id)
    
    logs = query.order_by(DialogueLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs

async def update_character_profile(db: Session, char_name: str, text: str):
    """
    后台任务：更新角色档案 (Deprecated).
    目前已被 `summarize_character` 主动触发模式取代。
    """
    chars = character_service.get_characters(db)
    target_char = next((c for c in chars if c.name == char_name), None)
    
    if target_char:
        new_info = await extraction_service.extract_character_info(text, char_name, target_char.attributes)
        if new_info:
            logger.info(f"更新角色 {char_name} 信息: {new_info}")
            updated_attrs = target_char.attributes.copy()
            updated_attrs.update(new_info)
            character_service.update_character(
                db, 
                target_char.id, 
                CharacterUpdate(attributes=updated_attrs, version_note="从对话中自动提取")
            )

from app.services.llm import llm_service

@router.get("/characters/{character_id}/versions", summary="获取角色历史版本")
def get_character_versions(character_id: int, db: Session = Depends(get_db)):
    """
    获取角色的所有历史版本存档。
    """
    versions = db.query(CharacterVersion).filter(CharacterVersion.character_id == character_id).order_by(CharacterVersion.version.desc()).all()
    return versions

@router.post("/characters/{character_id}/summarize", summary="一键总结并同步档案")
async def summarize_character(
    character_id: int,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    智能总结角色特征并同步到档案库 (Summarize & Sync Profile).
    
    核心流程:
    1. **获取记录 (Logs Retrieval)**: 获取指定角色或会话的近期对话记录。
    2. **LLM 分析 (LLM Analysis)**: 让LLM分析角色的性格(personality)、经历(background)、说话风格(speaking_style)。
    3. **深度合并 (Deep Merge)**: 将新的分析结果智能合并到现有的 `dynamic_profile` 中，保留旧有的独特信息，避免全量覆盖导致数据丢失。
    4. **版本控制 (Versioning)**: 自动创建新版本(Version +1)，便于回滚。
    
    Args:
        character_id (int): 目标角色ID
        session_id (str, optional): 指定会话ID，若为空则取最近50条记录
        
    Returns:
        dict: { "status": "success", "version": int, "summary": dict }
    """
    # 1. 获取角色对象 (Get Character)
    char_obj = character_service.get_character(db, character_id)
    if not char_obj:
        raise HTTPException(status_code=404, detail="Character not found")
        
    # 2. 获取对话记录 (Fetch Logs)
    # 如果提供了 session_id 则使用该会话的记录，否则使用该角色的最近50条记录
    query = db.query(DialogueLog)
    if session_id:
        query = query.filter(DialogueLog.session_id == session_id)
    else:
        # 默认策略：最近50条涉及该角色的记录
        query = query.filter(DialogueLog.character_id == character_id)
        
    logs = query.order_by(DialogueLog.created_at.desc()).limit(50).all()
    if not logs:
        return {"status": "skipped", "message": "No logs found for analysis"}
        
    # 准备 LLM 输入文本 (Prepare text for LLM)
    # 倒序排列，使其按时间正序 (Chronological order)
    logs.reverse()
    dialogue_text = ""
    for log in logs:
        dialogue_text += f"User: {log.user_input}\n"
        dialogue_text += f"Assistant: {log.bot_response}\n---\n"
        
    # 3. 构建 Prompt 并调用 LLM (Call LLM for Summary)
    # Load config from settings
    config = settings.PROMPTS.get("character_summary", {})
    prompt_template = config.get("prompt", "")
    
    # Use template from config
    system_prompt = prompt_template.format(
        character_name=char_obj.name,
        current_profile=json.dumps(char_obj.dynamic_profile, ensure_ascii=False)
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": dialogue_text}
    ]
    
    try:
        response = await llm_service.chat_completion(messages, response_format={"type": "json_object"})
        new_profile_data = json.loads(response)
        
        # 提取内部 Profile 数据 (Extract the inner profile)
        extracted_profile = new_profile_data.get("Dynamic Profile", new_profile_data)
        
        # --- 深度合并逻辑 (Deep Merge Logic) ---
        # 目标: 防止新生成的总结不完整导致旧有关键信息丢失。将新数据合并入旧数据。
        old_profile = char_obj.dynamic_profile or {}
        
        def deep_merge_profile(old_data, new_data):
            """
            递归合并字典和列表。
            - Dict: 递归合并键值。
            - List: 追加新元素并去重 (Set-based deduplication)。
            - Primitive: 仅当新值非空时覆盖。
            """
            if not isinstance(new_data, dict):
                return new_data if new_data else old_data
            
            # 从旧数据的副本开始 (Start with a copy of old data)
            merged = old_data.copy() if isinstance(old_data, dict) else {}
            
            for key, new_val in new_data.items():
                old_val = merged.get(key)
                
                # 如果新值为空，则跳过，保留旧值 (Skip empty new values)
                if not new_val:
                    continue
                
                if isinstance(new_val, dict) and isinstance(old_val, dict):
                    merged[key] = deep_merge_profile(old_val, new_val)
                elif isinstance(new_val, list) and isinstance(old_val, list):
                    # 列表合并策略：追加并去重 (Append & Deduplicate)
                    try:
                        existing_set = set()
                        safe_old_val = []
                        
                        # 处理旧列表 (Handle old list)
                        for item in old_val:
                            try:
                                if item not in existing_set:
                                    existing_set.add(item)
                                    safe_old_val.append(item)
                            except TypeError:
                                # 遇到不可哈希元素（如dict），直接保留
                                safe_old_val.append(item)
                        
                        # 处理新列表 (Handle new list)
                        for item in new_val:
                            try:
                                if item not in existing_set:
                                    safe_old_val.append(item)
                                    existing_set.add(item)
                            except TypeError:
                                safe_old_val.append(item)
                        
                        merged[key] = safe_old_val
                    except Exception:
                        # 兜底策略：直接拼接
                        merged[key] = old_val + new_val
                else:
                    # 基本类型：覆盖 (Overwrite)
                    merged[key] = new_val
            
            return merged

        final_profile = deep_merge_profile(old_profile, extracted_profile)
        
        # 4. 版本控制与更新 (Versioning & Update)
        # 归档旧版本 (Archive OLD profile)
        new_version_num = (char_obj.version or 1) + 1
        
        version_entry = CharacterVersion(
            character_id=char_obj.id,
            version=char_obj.version or 1,
            attributes_snapshot=char_obj.attributes,
            traits_snapshot=char_obj.traits,
            dynamic_profile_snapshot=char_obj.dynamic_profile, # 保存更新前的快照
            change_reason="Auto-summary update via /summarize"
        )
        db.add(version_entry)
        
        # 更新角色档案 (Update Character)
        updated_char = character_service.update_character(
            db, 
            character_id, 
            CharacterUpdate(
                dynamic_profile=final_profile,
                version=new_version_num,
                version_note=f"Auto-summary from session {session_id or 'recent'}"
            )
        )
        
        return {
            "status": "success", 
            "version": updated_char.version, 
            "summary": new_profile_data
        }
        
    except Exception as e:
        logger.error(f"Summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/knowledge/add", summary="添加知识", description="向向量数据库添加文档片段")
async def add_knowledge(text: str, doc_id: str, metadata: dict = {}):
    await knowledge_service.add_document(doc_id, text, metadata)
    return {"status": "success", "doc_id": doc_id}

class AnalysisRequest(BaseModel):
    text: str = Field(..., description="对话文本内容")
    character_names: List[str] = Field(default=[], description="已知角色名称列表 (用于辅助识别)")
    mode: Optional[str] = Field("deep", description="分析模式: deep (深度分析) | quick (快速摘要)")
    session_id: Optional[str] = Field(None, description="会话ID，用于关联观察记录")
    history_context: Optional[List[dict]] = Field(default=[], description="历史分析记录上下文")

@router.post("/analysis/conversation", summary="分析长对话")
async def analyze_conversation_endpoint(
    request: AnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    分析长对话内容 (Analyze Long Conversation).
    
    核心功能:
    1. **文本输入**: 接收一段长文本对话记录 (通常来自剪贴板或文件导入)。
    2. **自动降级**: 如果文本过短 (<50字符)，自动切换到 `quick` 模式以节省资源。
    3. **模式选择**:
        - `quick`: 快速摘要，仅提取核心话题和情绪概况。
        - `deep`: 深度分析，识别每个角色的关键点、潜在动机、心理状态，并生成可视化的关系图数据。
    4. **事件生成**: 在深度模式下，会自动提取并在数据库中生成“观察建议”(Observations)，供管理员审核。
    5. **综合分析**: 结合历史记录进行连贯性分析。
    
    Args:
        request (AnalysisRequest): 请求体，包含文本、角色名列表和分析模式。
        db (Session): 数据库会话 (用于深度模式下的数据持久化)。
        
    Returns:
        dict: 结构化的分析结果 (JSON)，包含摘要、角色分析详情、关系图数据等。
    """
    try:
        # 1. 自动降级检查 (Automatic degradation check)
        # 如果文本太短，强行使用深度分析不仅浪费 Token，效果也不好
        if len(request.text) < 50 and request.mode == "deep":
            logger.info("Input too short, auto-downgrading to quick mode.")
            request.mode = "quick"

        # 2. 执行分析 (Execute Analysis)
        if request.mode == "quick":
            # 快速模式：仅做简单摘要
            result = await extraction_service.quick_analyze(request.text)
        else:
            # 深度模式：调用 LLM 进行全面剖析，并传入 DB Session 以便自动保存“观察建议”
            # Pass db session to allow auto-generation of character events/observations
            result = await extraction_service.deep_analyze(
                request.text, 
                request.character_names, 
                db=db,
                history_context=request.history_context
            )
            
        # --- Persistence (Save to Database) ---
        try:
            structured_data = result.get("structured_data", {})
            summary = structured_data.get("summary", "")
            # If summary is missing in structured data, try to extract from markdown or use first few chars
            if not summary and "markdown_report" in result:
                 summary = result["markdown_report"][:200] + "..."
            
            new_log = AnalysisLog(
                session_id=request.session_id,
                text_content=request.text,
                character_names=request.character_names,
                summary=summary,
                markdown_report=result.get("markdown_report", ""),
                structured_data=structured_data
            )
            db.add(new_log)
            db.commit()
            db.refresh(new_log)
            
            # Append ID to result so frontend knows it is saved
            result["log_id"] = new_log.id
            
        except Exception as e:
            logger.error(f"Failed to save AnalysisLog: {e}")
            # Do not fail the request if saving fails, just log it
            
        return result
    except Exception as e:
        logger.error(f"Analysis endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Query
from sqlalchemy import or_, cast, String

@router.get("/analysis/history", summary="获取长对话历史分析记录")
def get_analysis_history(
    character_names: Optional[List[str]] = Query(None),
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    获取历史分析记录 (Get Analysis History).
    
    Args:
        character_names: 筛选包含特定角色的记录
        limit: 返回条数 (若为 -1，则返回全部)
    """
    query = db.query(AnalysisLog).order_by(AnalysisLog.created_at.desc())
    
    if character_names:
        # 使用数据库级筛选优化性能 (Database-level filtering)
        # 针对 JSON 类型的兼容性处理: 将 JSON 字段转换为字符串进行模糊匹配
        # 假设存储格式为 ["Name1", "Name2"]，匹配 "Name1"
        conditions = []
        for name in character_names:
            # 注意: 简单的 LIKE 匹配可能会有误判 (e.g. "Ann" matches "Anna")
            # 但在大多数情况下对于全名匹配是足够的，且比全表扫描+内存过滤高效得多
            conditions.append(cast(AnalysisLog.character_names, String).like(f'%"{name}"%'))
        
        if conditions:
            query = query.filter(or_(*conditions))
            
    if limit > 0:
        return query.limit(limit).all()
    return query.all()

from app.services.character_observation_service import character_observation_service

@router.get("/observations/pending", summary="获取待处理的观察建议")
def get_pending_observations(
    character_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    获取待处理的角色观察建议 (Pending Observations).
    
    功能描述:
    管理员可以通过此接口获取系统在对话分析过程中自动生成的“观察建议”。
    这些建议通常包含对角色性格、行为模式或人际关系的修正提议。
    
    Args:
        character_id (int, optional): 若指定，则只返回该角色的建议；否则返回所有待处理建议。
        db (Session): 数据库会话
        
    Returns:
        List[dict]: 待处理的观察建议列表
    """
    return character_observation_service.get_pending_observations(db, character_id)

@router.post("/observations/{observation_id}/approve", summary="批准观察建议")
def approve_observation(
    observation_id: int,
    db: Session = Depends(get_db)
):
    """
    批准某条观察建议并合并到角色档案 (Approve & Merge).
    
    核心逻辑:
    1. **状态更新**: 将观察建议的状态标记为 `approved`。
    2. **档案合并**: 将建议中的 `proposed_value` 自动合并到角色的 `dynamic_profile` 中。
       - 如果是列表字段 (如 core_drivers)，通常是追加。
       - 如果是单值字段，通常是覆盖。
    3. **版本记录**: 此操作可能会触发角色档案的版本更新。
    
    Args:
        observation_id (int): 观察建议ID
        
    Returns:
        dict: { "status": "approved" }
    """
    success = character_observation_service.approve_observation(db, observation_id)
    if not success:
        raise HTTPException(status_code=400, detail="Approval failed")
    return {"status": "approved"}

@router.post("/observations/{observation_id}/reject", summary="拒绝观察建议")
def reject_observation(
    observation_id: int,
    db: Session = Depends(get_db)
):
    """
    拒绝某条观察建议 (Reject).
    
    功能描述:
    管理员认为系统的观察建议不准确或不符合预期时，可以拒绝。
    拒绝后的建议将被标记为 `rejected`，不会影响角色档案，但会保留在数据库中作为系统优化的负样本。
    
    Args:
        observation_id (int): 观察建议ID
        
    Returns:
        dict: { "status": "rejected" }
    """
    success = character_observation_service.reject_observation(db, observation_id)
    if not success:
        raise HTTPException(status_code=400, detail="Rejection failed")
    return {"status": "rejected"}

@router.post("/characters/{character_id}/feedback", summary="提交角色画像反馈")
def submit_character_feedback(
    character_id: int,
    feedback_data: CharacterFeedbackInput,
    db: Session = Depends(get_db)
):
    """
    提交对角色画像准确性的反馈 (Submit Character Accuracy Feedback).
    
    功能描述:
    用户在与角色互动或查看角色档案时，可以对角色表现的准确性进行评价。
    这不同于对单轮对话质量的评分，而是针对角色长期人设一致性的反馈。
    
    Args:
        character_id (int): 角色ID
        feedback_data (CharacterFeedbackInput): 反馈内容，包含是否准确、原因分类、详细评论等。
        
    Returns:
        dict: { "status": "success", "id": int }
    """
    new_feedback = CharacterFeedback(
        character_id=character_id,
        session_id=feedback_data.session_id,
        log_id=feedback_data.log_id,
        is_accurate=1 if feedback_data.is_accurate else 0,
        reason_category=feedback_data.reason_category,
        comment=feedback_data.comment,
        context_data=feedback_data.context_data
    )
    db.add(new_feedback)
    db.commit()
    db.refresh(new_feedback)
    return {"status": "success", "id": new_feedback.id}

