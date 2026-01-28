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

    async def deep_analyze(self, text: str, character_names: List[str] = None, db: Session = None, history_context: str = None, audio_features: Dict = None, emotion_data: Dict = None, speaker_info: Dict = None):
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

        char_list_str = ", ".join(character_names) if character_names else "未知角色"
        
        prompt = f"""
        你是一位专业的心理侧写师和剧情分析专家。请对以下对话片段进行深度分析。
        
        【在场角色】
        {char_list_str}
        
        {speaker_context}
        {multimodal_context}
        
        【对话内容】
        {text}
        
        【分析要求】
        1. **剧情摘要**: 简要概括发生了什么。
        2. **多角色心理推演 (重点)**: 
           - 对每一位在场角色，分析其**潜台词 (Subtext)**、**内心独白 (Inner OS)** 和 **真实情绪 (Emotion)**。
           - 结合声学特征（如果有）来判断情绪的激动程度。
        3. **角色档案更新 (归档用)**:
           - 为每位角色提取**本次对话体现的特征/信息摘要 (Summary)**。
           - 提取 3-5 个**关键词标签 (Tags)**。
        4. **人际关系动态**: 角色之间的关系是否发生了变化？
        
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
                    "summary": "该角色本次对话的行为/信息摘要 (用于归档)...",
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
            # Extract JSON
            import re
            match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if match:
                try:
                    structured_data = json.loads(match.group(1))
                except:
                    pass
            
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
