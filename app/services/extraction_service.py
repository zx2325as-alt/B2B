import json
import re
import time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.services.llm import llm_service
from app.models.sql_models import Scenario, Character
from app.utils.logger import logger
from app.services.character_observation_service import character_observation_service
from app.services.character_service import character_service

class ExtractionService:
    async def detect_scenario(self, text: str, history: List[Dict], available_scenarios: List[Scenario]) -> Optional[int]:
        """
        Identify the most likely scenario from the available list based on conversation.
        Returns the Scenario ID.
        """
        if not available_scenarios:
            return None

        scenario_descriptions = [f"ID {s.id}: {s.name} - {s.description}" for s in available_scenarios]
        
        # Load config (Moved to deep_analysis.scenario_detection)
        config = settings.PROMPTS.get("deep_analysis", {}).get("scenario_detection", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.1)
        
        prompt = prompt_template.format(
            scenario_descriptions=chr(10).join(scenario_descriptions),
            text=text
        )
        
        response = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"}
        )
        
        try:
            result = json.loads(response)
            return result.get("scenario_id")
        except Exception as e:
            logger.error(f"Scenario detection failed: {e}")
            return None

    async def extract_character_info(self, text: str, character_name: str, existing_attributes: Dict) -> Dict[str, Any]:
        """
        Extract new information about a character from the text to update their profile.
        """
        # Load config (Moved to deep_analysis.character_info)
        config = settings.PROMPTS.get("deep_analysis", {}).get("character_info", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.1)

        prompt = prompt_template.format(
            character_name=character_name,
            existing_attributes=json.dumps(existing_attributes),
            text=text
        )
        
        response = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"}
        )
        
        try:
            return json.loads(response)
        except Exception as e:
            logger.error(f"Character info extraction failed: {e}")
            return {}

    async def process_analysis_results(self, db: Session, session_id: str, structured_data: Dict[str, Any]):
        """
        处理结构化分析结果 (Process Structured Analysis Results).
        
        功能描述:
        当 `deep_analyze` 生成结构化数据后，此方法负责将其转化为系统内部的持久化数据。
        这构成了系统的“主动感知”能力。
        
        包含三个核心支柱 (Three Pillars):
        1. **事件生成 (Event Generation)**: (代码中暂略) 自动识别关键剧情节点。
        2. **观察收集 (Observation Collection)**: 自动提取对角色的洞察，生成“待审核建议”。
        3. **关系推演 (Relationship Inference)**: 根据互动自动更新角色间的关系强度和情感倾向。
        
        Args:
            db (Session): 数据库会话
            session_id (str): 当前会话ID
            structured_data (dict): LLM 分析出的 JSON 数据
        """
        # --- Pillar 2: Auto-generate Character Events (自动生成角色事件) ---
        if db and "character_analysis" in structured_data:
            try:
                global_summary = structured_data.get("summary", "Deep Analysis Session")
                for char_data in structured_data["character_analysis"]:
                    char_name = char_data.get("name")
                    if not char_name:
                        continue
                        
                    # Find character ID by name
                    character = db.query(Character).filter(Character.name == char_name).first()
                    if character:
                        pass # 实际逻辑待实现，目前为占位符
            except Exception as e:
                logger.error(f"Failed to auto-generate character events: {e}")

        # --- Pillar 2.5: Auto-collect Character Observations (自动收集观察建议) ---
        # 这是“动态档案”的核心来源。系统自动发现角色的新特征，但不直接修改档案，
        # 而是生成“Pending Observations”供管理员审核。
        if db and session_id and "character_observations" in structured_data:
            try:
                observations = structured_data["character_observations"]
                if observations:
                    character_observation_service.add_observations(db, session_id, observations)
                    logger.info(f"Processed {len(observations)} character observations")
            except Exception as e:
                logger.error(f"Failed to process character observations: {e}")

        # --- Pillar 3: Relationship Inference Engine (关系推演引擎) ---
        # 自动量化角色间的互动影响。
        # strength_delta: 关系强度的变化 (如 +1 变得更紧密, -1 变得疏远)
        # sentiment_delta: 情感倾向的变化 (如 +1 变得更喜欢, -1 变得厌恶)
        if db and "relationship_updates" in structured_data:
            try:
                updates = structured_data["relationship_updates"]
                for update in updates:
                    source = update.get("source")
                    target = update.get("target")
                    s_delta = update.get("strength_delta", 0)
                    sent_delta = update.get("sentiment_delta", 0)
                    
                    if source and target:
                        character_service.update_relationship_state(
                            db, source, target, 
                            strength_delta=s_delta, 
                            sentiment_delta=sent_delta
                        )
                if updates:
                    logger.info(f"Processed {len(updates)} relationship updates")
            except Exception as e:
                logger.error(f"Failed to process relationship updates: {e}")

    async def deep_analyze(self, text: str, character_names: List[str], db: Session = None, session_id: str = None, history_context: List[dict] = None) -> Dict[str, Any]:
        """
        深度对话分析 (Deep Analysis).
        
        功能描述:
        调用 LLM 对长对话进行深度心理和战略分析。
        支持“混合输出模式”：同时返回 Markdown 格式的可读报告和 JSON 格式的结构化数据。
        
        稳定性机制 (Reliability):
        - **熔断机制 (Circuit Breaker)**: 如果深度分析调用失败 (如超时或 Token 超限)，
          自动降级调用 `quick_analyze`，确保用户总能获得基础结果。
        
        Args:
            text (str): 对话文本
            character_names (list): 已知角色名列表 (辅助 LLM 识别)
            db (Session, optional): 数据库会话 (用于持久化副作用)
            session_id (str, optional): 会话ID
            history_context (list, optional): 历史分析摘要列表，用于综合分析
            
        Returns:
            dict: { "markdown_report": str, "structured_data": dict, ... }
        """
        start_time = time.time()
        
        # Load config (deep_analysis.primary)
        config = settings.PROMPTS.get("deep_analysis", {}).get("primary", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.4)
        
        # Inject History Context if available
        history_text = ""
        if history_context:
            history_text = "\n\n【历史分析摘要 (History Context)】:\n"
            for i, record in enumerate(history_context):
                ts = record.get("timestamp", "Unknown Time")
                summary = record.get("summary", "No summary")
                history_text += f"Records[{i+1}] ({ts}): {summary}\n"
            history_text += "\n请结合上述历史上下文，对本次对话进行更深入的连贯性分析。\n"

        prompt = prompt_template.format(
            text=history_text + text,
            character_names=", ".join(character_names)
        )

        
        # Call LLM - NO JSON ENFORCEMENT for mixed output (Markdown + JSON)
        # 我们允许 LLM 自由输出 Markdown 文本，并在其中嵌入 ```json 代码块
        try:
            response = await llm_service.chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=temperature
                # response_format={"type": "json_object"} # Removed to allow Markdown
            )
        except Exception as e:
            logger.error(f"Deep Analysis LLM call failed: {e}. Switching to Circuit Breaker mode.")
            # --- 熔断机制 (Circuit Breaker) ---
            # 自动切换到快速模式 (Fallback to Quick Analyze)
            fallback_result = await self.quick_analyze(text)
            fallback_result["markdown_report"] = f"### 🛡️ 熔断机制已触发 (Circuit Breaker)\n\n> 检测到深度分析服务响应异常，已自动切换至摘要模式。\n\n" + fallback_result["markdown_report"]
            return fallback_result
        
        duration = time.time() - start_time
        logger.info(f"Deep Analysis completed in {duration:.2f}s. Input length: {len(text)}")
        
        if not response:
            return {"error": "LLM returned empty response"}
            
        # Parse Mixed Output: Extract JSON block
        # 使用正则提取 Markdown 中的 JSON 代码块
        json_pattern = r"```json\s*(\{.*?\})\s*```"
        match = re.search(json_pattern, response, re.DOTALL)
        
        if match:
            json_str = match.group(1)
            # The report is everything EXCEPT the JSON block
            # 报告内容 = 原始回复 - JSON块
            markdown_report = response.replace(match.group(0), "").strip()
            try:
                structured_data = json.loads(json_str)
            except json.JSONDecodeError:
                structured_data = {"error": "Failed to parse JSON part"}
        else:
            # Fallback: Treat whole response as markdown, no structured data found
            # 未发现 JSON 块，则认为全是文本报告
            markdown_report = response
            structured_data = {}
            
        # Process Results using shared method (触发副作用：生成观察、更新关系)
        if db and session_id:
            await self.process_analysis_results(db, session_id, structured_data)
            
        return {
            "markdown_report": markdown_report,
            "structured_data": structured_data,
            "metrics": {
                "duration": duration,
                "input_chars": len(text)
            }
        }

    async def quick_analyze(self, text: str) -> Dict[str, Any]:
        """
        Perform quick analysis (Degradation Mode).
        """
        start_time = time.time()
        
        config = settings.PROMPTS.get("deep_analysis", {}).get("quick_parse", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.2)
        
        prompt = prompt_template.format(text=text)
        
        response = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"}
        )
        
        duration = time.time() - start_time
        logger.info(f"Quick Analysis completed in {duration:.2f}s")
        
        try:
            structured_data = json.loads(response)
        except:
            structured_data = {"summary": "解析失败", "error": "Invalid JSON"}
            
        return {
            "markdown_report": f"### ⚡ 快速分析报告 (降级模式)\n\n**摘要**: {structured_data.get('summary', '无')}\n\n*(注：由于系统负载或网络原因，已自动切换为快速模式)*",
            "structured_data": structured_data,
            "mode": "quick",
            "metrics": {
                "duration": duration,
                "input_chars": len(text)
            }
        }

extraction_service = ExtractionService()
