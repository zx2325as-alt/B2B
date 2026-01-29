import logging
import json
import time
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.services.llm import llm_service
from app.services.knowledge import knowledge_service

logger = logging.getLogger(__name__)

class ExtractionService:
    
    async def quick_analyze(self, text: str) -> Dict:
        """
        Quick analysis: Summary and Sentiment.
        """
        prompt = f"""
        请对以下对话文本进行快速分析：
        1. 生成简短摘要 (Summary)
        2. 识别整体情感倾向 (Sentiment)

        文本内容：
        {text}

        请以 JSON 格式返回：
        {{
            "summary": "...",
            "sentiment": "..."
        }}
        """
        try:
            response = await llm_service.chat_completion([{"role": "user", "content": prompt}])
            # Try to parse JSON, fallback to raw text if failed
            try:
                data = json.loads(response)
            except:
                # If LLM returns markdown code block
                if "```json" in response:
                    import re
                    match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                    else:
                        data = {"summary": response, "sentiment": "unknown"}
                else:
                    data = {"summary": response, "sentiment": "unknown"}
            
            return {
                "markdown_report": f"### 快速摘要\n{data.get('summary')}\n\n### 情感倾向\n{data.get('sentiment')}",
                "structured_data": data
            }
        except Exception as e:
            logger.error(f"Quick analyze failed: {e}")
            return {"markdown_report": "Analysis failed.", "structured_data": {}}

    async def deep_analyze(self, text: str, character_names: List[str] = None, db: Session = None, history_context: List[Dict] = None, audio_features: Dict = None, emotion_data: Dict = None, speaker_info: Dict = None, character_profiles: List[Dict] = None, dialogue_history: List[Dict] = None):
        """
        Deep analysis: Multi-role deduction, Inner OS, Emotion, etc.
        """
        
        # Format Audio/Multimodal Context
        multimodal_context = ""
        if audio_features or emotion_data:
            multimodal_context += "\n【多模态感知数据】\n"
            
            # 1. Acoustic Features
            if audio_features:
                pitch = audio_features.get('pitch', 0)
                energy = audio_features.get('energy', 0)
                duration = audio_features.get('duration', 0)
                # Simple heuristics for context
                pitch_desc = "偏高 (可能激动/紧张)" if pitch > 200 else "正常"
                energy_desc = "强 (声音洪亮)" if energy > 0.1 else "正常"
                
                multimodal_context += f"- 声学特征: 音高={pitch:.1f}Hz ({pitch_desc}), 能量={energy:.3f} ({energy_desc}), 时长={duration:.1f}s\n"
            
            # 2. Emotion Recognition (SER)
            if emotion_data:
                top_emotion = emotion_data.get('top_emotion', 'neutral')
                scores = emotion_data.get('emotions', {})
                # Format scores like: happy(0.8), sad(0.1)
                score_str = ", ".join([f"{k}({v:.2f})" for k, v in scores.items() if v > 0.2])
                multimodal_context += f"- 语音情感识别 (SER): 主导情绪=**{top_emotion}** [{score_str}]\n"
                
            multimodal_context += "请将上述感知数据作为重要参考，修正对角色真实情绪和潜台词的判断。\n"

        # Speaker Info
        speaker_context = ""
        if speaker_info:
            spk_name = speaker_info.get('name', 'Unknown')
            spk_id = speaker_info.get('id', 'unknown')
            speaker_context = f"【说话人身份】: {spk_name} (ID: {spk_id})\n"

        # History Context (Analysis Summaries)
        history_str = ""
        if history_context:
            history_str = "\n【历史背景与过往分析 (Summaries)】\n"
            # User requested all history, removing [-5:] limit
            for item in history_context: 
                ts = item.get("timestamp", "Unknown Time")
                summ = item.get("summary", "")
                if summ:
                    history_str += f"- [{ts}] {summ}\n"
            history_str += "请参考上述历史背景，确保本次分析与过往剧情连贯，并注意人物关系的变化。\n"
        
        # Dialogue History (Raw Speech) - New
        dialogue_history_str = ""
        if dialogue_history:
             dialogue_history_str = "\n【角色过往对话记录 (Raw Speech)】\n"
             # Assuming dialogue_history contains objects like { "character": "...", "text": "...", "timestamp": "..." }
             for item in dialogue_history:
                 char = item.get("character", "Unknown")
                 content = item.get("text", "")
                 ts = item.get("timestamp", "")
                 if content:
                     dialogue_history_str += f"- [{ts}] {char}: {content}\n"
             dialogue_history_str += "请参考角色过往的说话风格、用词习惯以及曾表达过的观点。\n"

        # Known Character Metrics (New)
        known_metrics_str = ""
        if character_profiles:
            known_metrics_str = "\n【已知角色档案 (Reference)】\n"
            for p in character_profiles:
                p_name = p.get('name', 'Unknown')
                # Try to get simplified summary or key metrics to save tokens
                metrics_summary = {
                    "basic_attributes": p.get("attributes", {}),
                    "personality_traits": p.get("traits", {}),
                    # Dynamic profile parts
                    "surface_behavior": p.get("dynamic_profile", {}).get("surface_behavior", {}),
                    "emotional_traits": p.get("dynamic_profile", {}).get("emotional_traits", {}),
                    "cognitive_decision": p.get("dynamic_profile", {}).get("cognitive_decision", {}),
                    "core_essence": p.get("dynamic_profile", {}).get("core_essence", {}),
                    "character_arc": p.get("dynamic_profile", {}).get("character_arc", [])
                }
                known_metrics_str += f"### 角色: {p_name}\n{json.dumps(metrics_summary, ensure_ascii=False, indent=2)}\n"

        char_list_str = ", ".join(character_names) if character_names else "未知角色"
        
        prompt = f"""
        你是一位专业的心理侧写师和剧情分析专家。请对以下对话片段进行深度分析。
        
        【在场角色】
        {char_list_str}
        
        {speaker_context}
        {multimodal_context}
        {history_str}
        {dialogue_history_str}
        {known_metrics_str}
        
        【对话内容】
        {text}
        
        【分析要求】
        1. **剧情摘要**: 简要概括发生了什么。
        2. **多角色心理推演 (重点)**: 
           - 对每一位在场角色，分析其**潜台词 (Subtext)**、**内心独白 (Inner OS)** 和 **真实情绪 (Emotion)**。
           - 结合声学特征（如果有）来判断情绪的激动程度。
        3. **角色档案更新 (Character Metrics Update)**:
           - 请参考【已知角色档案】，严格按照以下 6 个维度提取**新的**或**修正的**信息。
           - 若某维度在本次对话中无新信息，则留空。
             1. **基础属性 (Basic Attributes)**: 身份标签、成长经历、客观边界
             2. **表层行为 (Surface Behavior)**: 沟通模式、行为习惯、社交风格
             3. **情绪特征 (Emotional Traits)**: 情绪基线、情绪触发点、情绪表达、情绪调节
             4. **认知决策 (Cognitive Decision)**: 决策风格、思维模式、判断标准、信息处理
             5. **人格特质 (Personality Traits)**: 核心性格、特质倾向、三观底色、行为一致性
             6. **核心本质 (Core Essence)**: 核心驱动力、动机来源、深层需求、行为底线
             
             *注意：请重点关注**变化**、**新发现**或**深层动机的暴露**。*
        
        4. **人物弧光 (Character Arc) 分析**:
           - 识别角色是否经历了成长、退步或观念转变？
           - 记录关键的**转折点 (Turning Point)** 或 **里程碑 (Milestone)**。
           - 格式：请生成一段简短的描述，用于记录在角色成长时间线上。

        5. **人际关系动态**: 角色之间的关系是否发生了变化？
        
        请输出一份 Markdown 格式的报告（**必须使用简体中文**），并包含一个 JSON 代码块以便程序提取结构化数据。
        
        JSON 格式示例：
        ```json
        {{
            "summary": "剧情摘要...",
            "characters": [
                {{
                    "name": "角色名",
                    "inner_os": "内心独白...",
                    "emotion": "真实情绪...",
                    "subtext": "潜台词...",
                    "metrics": {{
                        "basic_attributes": {{ "identity": "...", "background": "..." }},
                        "surface_behavior": {{ "communication_style": "..." }},
                        "emotional_traits": {{ ... }},
                        "cognitive_decision": {{ ... }},
                        "personality_traits": {{ ... }},
                        "core_essence": {{ ... }}
                    }},
                    "character_arc": {{
                         "event": "事件描述...",
                         "type": "Growth/Regression/Stasis/Turning Point",
                         "timestamp": "当前时间或对话时间"
                    }},
                    "summary": "该角色本次对话的行为/信息摘要...",
                    "tags": ["标签1", "标签2"]
                }}
            ],
            "relationship_changes": "..."
        }}
        ```
        """
        
        try:
            response = await llm_service.chat_completion([{"role": "user", "content": prompt}])
            
            structured_data = {}
            # Extract JSON - Robust
            import re
            
            json_str = ""
            # 1. Try standard markdown code block
            match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL | re.IGNORECASE)
            if match:
                json_str = match.group(1)
            else:
                # 2. Try raw JSON (find first { and last })
                p1 = response.find('{')
                p2 = response.rfind('}')
                if p1 != -1 and p2 != -1:
                    json_str = response[p1:p2+1]
            
            if json_str:
                try:
                    structured_data = json.loads(json_str)
                except json.JSONDecodeError:
                    logger.warning(f"JSON decode error, raw: {json_str[:100]}...")
                    # --- Retry Mechanism (Self-Correction) ---
                    try:
                        logger.info("Attempting to repair JSON with LLM...")
                        repair_prompt = f"""
                        The following JSON is invalid. Please fix it and return ONLY the valid JSON object.
                        
                        {json_str}
                        """
                        repair_response = await llm_service.chat_completion([{"role": "user", "content": repair_prompt}])
                        
                        # Try extract again
                        match_r = re.search(r'```json\s*(.*?)\s*```', repair_response, re.DOTALL | re.IGNORECASE)
                        json_str_r = match_r.group(1) if match_r else repair_response
                        
                        # Strip non-json chars just in case
                        p1_r = json_str_r.find('{')
                        p2_r = json_str_r.rfind('}')
                        if p1_r != -1 and p2_r != -1:
                            json_str_r = json_str_r[p1_r:p2_r+1]
                            
                        structured_data = json.loads(json_str_r)
                        logger.info("JSON successfully repaired.")
                    except Exception as e_repair:
                        logger.error(f"JSON repair failed: {e_repair}")
                        pass
                    # -----------------------------------------
            else:
                 # --- No JSON Found: Retry Extraction ---
                 try:
                     logger.info("No JSON found in response. Attempting extraction from raw text...")
                     extract_prompt = f"""
                     Please extract the structured data (JSON) from the following text. 
                     Return ONLY the JSON object matching the previously defined schema.
                     
                     {response}
                     """
                     extract_response = await llm_service.chat_completion([{"role": "user", "content": extract_prompt}])
                     
                     match_e = re.search(r'```json\s*(.*?)\s*```', extract_response, re.DOTALL | re.IGNORECASE)
                     json_str_e = match_e.group(1) if match_e else extract_response
                     
                     p1_e = json_str_e.find('{')
                     p2_e = json_str_e.rfind('}')
                     if p1_e != -1 and p2_e != -1:
                         json_str_e = json_str_e[p1_e:p2_e+1]
                         
                     structured_data = json.loads(json_str_e)
                     logger.info("JSON successfully extracted via secondary prompt.")
                 except Exception as e_extract:
                     logger.error(f"Secondary extraction failed: {e_extract}")
                     pass
                 # ---------------------------------------
            
            return {
                "markdown_report": response,
                "structured_data": structured_data
            }
            
        except Exception as e:
            logger.error(f"Deep analyze failed: {e}")
            return {
                "markdown_report": f"Analysis failed: {str(e)}", 
                "structured_data": {}
            }

    async def summarize_session_segment(self, db: Session, session_id: str, last_n: int = 10):
        """
        Summarize the last N turns of a session and index it.
        """
        from app.models.sql_models import DialogueLog
        from app.services.knowledge import knowledge_service
        
        # 1. Fetch Logs
        logs = db.query(DialogueLog).filter(DialogueLog.session_id == session_id).order_by(DialogueLog.created_at.desc()).limit(last_n).all()
        if not logs:
            return

        logs.reverse() # Chronological
        
        text_block = ""
        for log in logs:
            text_block += f"User: {log.user_input}\nAssistant: {log.bot_response}\n\n"
            
        # 2. Call LLM
        prompt = f"""
        请对以下对话片段进行简要摘要（Summary），概括主要话题、决策和情感走向。
        
        {text_block}
        
        摘要：
        """
        
        try:
            summary = await llm_service.chat_completion([{"role": "user", "content": prompt}])
            
            # 3. Index
            # Create a virtual doc_id
            timestamp = int(time.time())
            doc_id = f"summary_{session_id}_{timestamp}"
            
            metadata = {
                "type": "summary",
                "session_id": session_id,
                "timestamp": str(timestamp)
            }
            
            await knowledge_service.add_document(doc_id, summary, metadata)
            logger.info(f"Indexed summary for session {session_id}")
            
        except Exception as e:
            logger.error(f"Summary indexing failed: {e}")

    async def extract_character_info(self, text: str, char_name: str, current_attributes: Dict) -> Dict:
        """
        Extract new information about a character from text.
        """
        prompt = f"""
        你是一个信息提取助手。请从以下文本中提取关于角色【{char_name}】的新信息（如外貌、性格、经历、喜好等）。
        
        当前已知属性:
        {json.dumps(current_attributes, ensure_ascii=False)}
        
        文本内容:
        {text}
        
        请判断文本中是否包含值得更新的新信息。
        如果是，请返回一个 JSON 对象，包含需要更新或新增的字段。
        如果否，请返回 {{}}。
        
        JSON 格式示例:
        {{
            "likes": "Apple",
            "background": "Born in 1990"
        }}
        """
        try:
            response = await llm_service.chat_completion([{"role": "user", "content": prompt}])
            import re
            match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)

            if match:
                return json.loads(match.group(1))
            # Try direct parse
            try:
                return json.loads(response)
            except:
                return {}
        except Exception as e:
            logger.error(f"Extract info failed: {e}")
            return {}

    async def process_analysis_results(self, db: Session, session_id: str, parsed_resp: Dict):
        """
        Process the structured response from the bot (e.g. update state, extract info).
        """
        # Example: If the bot's response contains explicit updates or facts
        # For now, we mainly use this hook to trigger side-effects if needed
        pass

extraction_service = ExtractionService()
