import json
import re
import time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.services.llm import llm_service
from app.models.sql_models import Scenario, Character
from app.utils.logger import logger

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

    async def deep_analyze(self, text: str, character_names: List[str], db: Session = None) -> Dict[str, Any]:
        """
        Perform deep psychological and strategic analysis on the conversation.
        
        Args:
            text: Conversation text
            character_names: List of known character names
            db: Database session (optional, for saving events)

        Returns:
            Dict[str, Any]: Contains 'markdown_report' (thinking process) and 'structured_data' (JSON result).
        """
        start_time = time.time()
        
        # Load config (deep_analysis.primary)
        config = settings.PROMPTS.get("deep_analysis", {}).get("primary", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.4)
        
        prompt = prompt_template.format(
            text=text,
            character_names=", ".join(character_names)
        )
        
        # Call LLM - NO JSON ENFORCEMENT for mixed output (Markdown + JSON)
        try:
            response = await llm_service.chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=temperature
                # response_format={"type": "json_object"} # Removed to allow Markdown
            )
        except Exception as e:
            logger.error(f"Deep Analysis LLM call failed: {e}. Switching to Circuit Breaker mode.")
            # Circuit Breaker: Fallback to Quick Analyze
            fallback_result = await self.quick_analyze(text)
            fallback_result["markdown_report"] = f"### 🛡️ 熔断机制已触发 (Circuit Breaker)\n\n> 检测到深度分析服务响应异常，已自动切换至摘要模式。\n\n" + fallback_result["markdown_report"]
            return fallback_result
        
        duration = time.time() - start_time
        logger.info(f"Deep Analysis completed in {duration:.2f}s. Input length: {len(text)}")
        
        if not response:
            return {"error": "LLM returned empty response"}
            
        # Parse Mixed Output: Extract JSON block
        json_pattern = r"```json\s*(\{.*?\})\s*```"
        match = re.search(json_pattern, response, re.DOTALL)
        
        if match:
            json_str = match.group(1)
            # The report is everything EXCEPT the JSON block
            markdown_report = response.replace(match.group(0), "").strip()
            try:
                structured_data = json.loads(json_str)
            except json.JSONDecodeError:
                structured_data = {"error": "Failed to parse JSON part"}
        else:
            # Fallback: Treat whole response as markdown, no structured data found
            markdown_report = response
            structured_data = {}
            
        # --- Pillar 2: Auto-generate Character Events ---
        if db and "character_analysis" in structured_data:
            try:
                global_summary = structured_data.get("summary", "Deep Analysis Session")
                for char_data in structured_data["character_analysis"]:
                    char_name = char_data.get("name")
                    if not char_name:
                        continue
                        
                    # Find character ID by name
                    # Note: Ideally we should pass IDs, but name lookup is acceptable here
                    character = db.query(Character).filter(Character.name == char_name).first()
                    if character:
                        feedback_service.add_character_event(
                            db=db,
                            character_id=character.id,
                            summary=global_summary,
                            intent=char_data.get("deep_intent"),
                            strategy=char_data.get("strategy")
                        )
                        logger.info(f"Auto-generated event for character {char_name}")
            except Exception as e:
                logger.error(f"Failed to auto-generate character events: {e}")

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
