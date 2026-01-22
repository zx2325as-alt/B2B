import json
from app.services.llm import llm_service
from app.models.schemas import DialogueInput, NLUOutput
from app.utils.logger import logger
from app.core.config import settings

class NLUEngine:
    DEFAULT_SYSTEM_PROMPT = """
    你是 BtB 系统的“意图路由中枢”。
    
    你的核心任务是判断用户的输入是：
    1. **CHAT**: 想和你（顾问）讨论、咨询、闲聊。
    2. **ANALYSIS**: 扔给你一段对话文本（通常包含引号、多个人物），要求你进行分析。
    3. **SYSTEM_OP**: 要求修改配置、查询记忆、存入信息等。
    
    输出 JSON:
    {
        "intent": "chat | analysis | system_op",
        "sub_intent": "string (optional)",
        "emotion": "string",
        "reasoning": "string",
        "slots": { "key": "value" },
        "implicit_hint": "string",
        "need_clarification": boolean,
        "clarification_question": "string (optional)"
    }
    """

    def __init__(self):
        nlu_config = settings.PROMPTS.get("nlu", {})
        self.system_prompt = nlu_config.get("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
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
