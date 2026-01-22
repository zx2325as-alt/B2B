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
from app.models.schemas import DialogueInput, NLUOutput
from app.models.sql_models import DialogueLog, Relationship, Scenario, ConversationSession
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
    采用流式响应 (Streaming Response) 模式，分阶段返回数据。
    
    Args:
        input_data (DialogueInput): 用户输入数据(文本、会话ID等)
        background_tasks (BackgroundTasks): 后台任务队列
        db (Session): 数据库会话
        
    Flow:
        1. **Session Sync**: 确保请求上下文与数据库会话状态一致。
        2. **NLU Analysis**: 调用 `nlu_engine` 分析用户意图(Intent)和情感。
        3. **Context Build**: 调用 `context_manager` 聚合所有相关上下文(角色、知识库、记忆)。
        4. **Generation**: 调用 `dialogue_service` 生成回复。
        5. **Streaming**: 
            - Chunk 1: NLU分析结果 (JSON)
            - Chunk 2: 思考过程/意图分析 (Text/JSON)
            - Chunk 3: 最终回复 (Text)
            - Chunk 4: 元数据(Log ID) (JSON)
            
    Returns:
        StreamingResponse: application/x-ndjson 格式的流式数据。
    """
    start_time = time.time()
    
    # 0. Session Handling
    session_obj = None
    if input_data.session_id:
        session_obj = db.query(ConversationSession).filter(ConversationSession.id == input_data.session_id).first()
        if session_obj:
            session_obj.updated_at = func.now()
            # Sync context from session if missing in input
            if not input_data.character_id and session_obj.character_id:
                input_data.character_id = session_obj.character_id
            if not input_data.scenario_id and session_obj.scenario_id:
                input_data.scenario_id = session_obj.scenario_id
            db.commit()
    
    # Pre-fetch Character Name for NLU Context
    if input_data.character_id:
        char_obj = character_service.get_character(db, input_data.character_id)
        if char_obj:
            input_data.character_name = char_obj.name

    # 1. NLU Analysis (Fast)
    logger.info(f"正在分析输入: {input_data.text} (Character: {input_data.character_name})")
    nlu_result = await nlu_engine.analyze(input_data)
    
    if nlu_result.need_clarification:
        return {
            "response": nlu_result.clarification_question,
            "nlu_analysis": nlu_result.dict(),
            "type": "clarification"
        }

    # 2. Context Management (The "Context Manager")
    # Build rich context using the dedicated service
    
    # Create a temporary session object if one doesn't exist to pass to context manager
    # (Or modify ContextManager to accept IDs. For now, we wrap.)
    if not session_obj:
        # Create ephemeral session structure for context manager
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
    
    # Force Local Scenario Override (Development Feature)
    local_scenario_path = r"e:\python\conda\PyTorch01\BtB\scenarios\hr_assistant.yaml"
    local_scenario = load_local_scenario(local_scenario_path)
    if local_scenario:
         # Use local scenario if available, but keep context
         current_scenario = local_scenario
         logger.info(f"Using local scenario override: {local_scenario.name}")

    # 3. Intent Routing (System Ops)
    system_intent = nlu_result.intent == "system_op"
    sub_intent = nlu_result.sub_intent
    
    # 4. User Profile
    profile = user_service.get_profile(input_data.user_id)
    
    # 5. Async Generator for Streaming Response
    async def response_generator():
        # Yield Analysis Data First
        analysis_data = {
            "nlu_analysis": nlu_result.dict(),
            "scenario": current_scenario.name if current_scenario else None,
            "context_used": context_docs,
            "type": "streaming",
            "session_id": input_data.session_id
        }
        yield json.dumps(analysis_data, ensure_ascii=False) + "\n"
        
        # Call Generation Service
        final_response_text = ""
        reasoning_content = None
        
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
            
            # Parse logic
            final_response_text = raw_response
            try:
                parsed_resp = json.loads(raw_response)
                if isinstance(parsed_resp, dict):
                    # 1. Use Thinking Process as the Main Response
                    thinking_process = parsed_resp.get("thinking_process")
                    
                    if thinking_process:
                        final_response_text = thinking_process
                    else:
                        # Fallback if no thinking process
                        pa = parsed_resp.get("primary_analysis", {})
                        speaker = pa.get("speaker", "未知")
                        intent = pa.get("intent_analysis", "分析中...")
                        final_response_text = f"**【{speaker}】意图分析**\n{intent}"
                    
                    # 2. Append Suggested Responses (If any exist, though user asked to remove them or advisor comment)
                    # User said "局势总结内容太水了取消", referring to advisor_comment.
                    # We removed advisor_comment from prompt.
                    # Suggested responses are also removed from prompt.
                    
                    # So mostly final_response_text is just thinking_process.

                    
                    # Common Reasoning Extraction
                    if parsed_resp.get("primary_analysis"):
                        reasoning_content = parsed_resp
                    else:
                        reasoning_content = (
                            parsed_resp.get("analysis") or 
                            parsed_resp.get("thought_process") or 
                            parsed_resp.get("reasoning")
                        )
                    # Do NOT dump to string here, let the outer json.dumps handle it
                    # so frontend receives a real object
                    # if isinstance(reasoning_content, dict):
                    #    reasoning_content = json.dumps(reasoning_content, ensure_ascii=False, indent=2)
            except:
                pass

            # Yield Final Response
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

        # Background Tasks (Logging)
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
                
                # Yield Log ID for Frontend Feedback
                yield json.dumps({"type": "meta", "log_id": log_entry.id}, ensure_ascii=False) + "\n"
                
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

@router.post("/characters/{character_id}/summarize", summary="一键总结并同步档案")
async def summarize_character(
    character_id: int,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    智能总结角色特征并同步到档案库 (Summarize & Sync Profile).
    
    功能:
    1. **Logs Retrieval**: 获取指定角色或会话的近期对话记录。
    2. **LLM Analysis**: 让LLM分析角色的性格(personality)、经历(background)、说话风格(speaking_style)。
    3. **Profile Update**: 将分析结果合并到角色的 `dynamic_profile` 字段。
    4. **Versioning**: 自动创建新版本(Version +1)，便于回滚。
    
    Args:
        character_id (int): 目标角色ID
        session_id (str, optional): 指定会话ID，若为空则取最近50条记录
        
    Returns:
        dict: { "status": "success", "version": int, "summary": dict }
    """
    # 1. Get Character
    char_obj = character_service.get_character(db, character_id)
    if not char_obj:
        raise HTTPException(status_code=404, detail="Character not found")
        
    # 2. Fetch Logs
    # If session_id provided, use that. Otherwise use recent logs for this character.
    query = db.query(DialogueLog)
    if session_id:
        query = query.filter(DialogueLog.session_id == session_id)
    else:
        # Just last 50 logs involving this character
        query = query.filter(DialogueLog.character_id == character_id)
        
    logs = query.order_by(DialogueLog.created_at.desc()).limit(50).all()
    if not logs:
        return {"status": "skipped", "message": "No logs found for analysis"}
        
    # Prepare text for LLM
    # Reverse to chronological order
    logs.reverse()
    dialogue_text = ""
    for log in logs:
        dialogue_text += f"User: {log.user_input}\n"
        dialogue_text += f"Assistant: {log.bot_response}\n---\n"
        
    # 3. Call LLM for Summary
    system_prompt = f"""
你是一个角色档案管理员。请根据以下对话记录，提取并总结角色【{char_obj.name}】的最新特征。
请返回一个 JSON 对象，包含需要更新的字段。

当前档案 (仅供参考):
{json.dumps(char_obj.dynamic_profile, ensure_ascii=False)}

【要求】
1. 提取性格标签 (personality_tags)
2. 提取关键经历/事实 (background)
3. 提取说话风格 (speaking_style)
4. 输出 JSON 格式：{{ "personality_tags": [...], "background": "...", "speaking_style": "..." }}
5. 如果没有新信息，保持原样。
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": dialogue_text}
    ]
    
    try:
        response = await llm_service.chat_completion(messages, response_format={"type": "json_object"})
        new_profile_data = json.loads(response)
        
        # Merge with existing dynamic_profile
        current_profile = char_obj.dynamic_profile or {}
        
        # Simple Merge Strategy: Overwrite keys provided by LLM, keep others
        # Ideally, we should append tags, but for now overwrite/update is safer to avoid duplication if LLM returns all
        current_profile.update(new_profile_data)
        
        # 4. Update Character
        updated_char = character_service.update_character(
            db, 
            character_id, 
            CharacterUpdate(
                dynamic_profile=current_profile,
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
    character_names: List[str] = Field(default=[], description="已知角色名称列表")
    mode: Optional[str] = Field("deep", description="分析模式: deep (深度) | quick (快速)")

@router.post("/analysis/conversation", summary="分析长对话")
async def analyze_conversation_endpoint(
    request: AnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    分析长对话内容 (Analyze Long Conversation).
    
    功能:
    1. 接收长文本对话记录。
    2. 识别角色并区分对话内容。
    3. 分析每个角色的关键点、情绪/心情。
    4. 返回结构化的分析结果。
    
    Args:
        request (AnalysisRequest): 包含文本内容、已知角色名称列表和模式。
        
    Returns:
        dict: 结构化的分析结果 (JSON)。
    """
    try:
        # Automatic degradation check: If text is too short (< 50 chars), switch to quick mode
        if len(request.text) < 50 and request.mode == "deep":
            logger.info("Input too short, auto-downgrading to quick mode.")
            request.mode = "quick"

        if request.mode == "quick":
            result = await extraction_service.quick_analyze(request.text)
        else:
            # Pass db session to allow auto-generation of character events
            result = await extraction_service.deep_analyze(request.text, request.character_names, db=db)
            
        return result
    except Exception as e:
        logger.error(f"Analysis endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

