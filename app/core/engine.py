import json
from app.services.llm import llm_service
from app.models.schemas import DialogueInput, NLUOutput
from app.utils.logger import logger
from app.core.config import settings

class NLUEngine:
    def __init__(self):
        nlu_config = settings.PROMPTS.get("nlu", {})
        # Default fallback if config fails
        fallback = "你是意图识别助手。请输出 JSON 包含 intent (chat/analysis/system_op), emotion, reasoning。"
        self.system_prompt = nlu_config.get("system_prompt", fallback)
        self.temperature = nlu_config.get("temperature", 0.2)

    async def analyze(self, input_data: DialogueInput) -> NLUOutput:
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Add context info
        context_info = ""
        if input_data.character_name:
            context_info += f"【当前选中角色】: {input_data.character_name} (ID: {input_data.character_id})\n"
        
        if context_info:
             messages.append({"role": "system", "content": f"上下文信息：\n{context_info}"})

        # Add history context
        for msg in input_data.history[-5:]: # Keep last 5 turns
            messages.append(msg)
            
        messages.append({"role": "user", "content": input_data.text})

        # Call LLM
        # We enforce JSON mode if supported, otherwise rely on prompt
        json_response = await llm_service.chat_completion(
            messages, 
            temperature=self.temperature, 
            response_format={"type": "json_object"}
        )
        
        try:
            if not json_response:
                raise ValueError("Empty response from LLM")
            parsed = json.loads(json_response)
            return NLUOutput(**parsed)
        except Exception as e:
            logger.exception(f"Failed to parse NLU response. Raw Response: {json_response}")
            # Fallback Mock Response for Robustness
            return NLUOutput(
                intent="unknown",
                emotion="neutral",
                reasoning="System encountered an error connecting to the AI model. Returning fallback response.",
                need_clarification=False, # Avoid stuck loop
                implicit_hint="System Error",
                slots={}
            )

nlu_engine = NLUEngine()
