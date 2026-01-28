import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.extraction_service import ExtractionService

# Mock LLM response for Deep Analysis (includes markdown text + json block)
MOCK_DEEP_ANALYSIS_RESPONSE = """
### Deep Analysis Report
Here is the analysis of the situation.

```json
{
    "summary": "The user is expressing doubt.",
    "characters": [
        {
            "name": "Hero",
            "inner_os": "He seems hesitant.",
            "emotion": "Anxious",
            "subtext": "He wants to ask for help but is afraid."
        }
    ],
    "relationship_changes": "Trust building up."
}
```
"""

# Mock LLM response for Quick Analysis
MOCK_QUICK_ANALYSIS_RESPONSE = json.dumps({
    "summary": "User asked about the weather.",
    "sentiment": "Neutral"
})

@pytest.fixture
def extraction_service():
    return ExtractionService()

@pytest.mark.asyncio
async def test_quick_analyze(extraction_service):
    # Mock llm_service.chat_completion
    with patch("app.services.extraction_service.llm_service") as mock_llm:
        mock_llm.chat_completion = AsyncMock(return_value=MOCK_QUICK_ANALYSIS_RESPONSE)
        
        result = await extraction_service.quick_analyze("How is the weather today?")
        
        # Verify result structure
        assert "structured_data" in result
        assert result["structured_data"]["summary"] == "User asked about the weather."
        assert result["structured_data"]["sentiment"] == "Neutral"
        assert "markdown_report" in result

@pytest.mark.asyncio
async def test_deep_analyze(extraction_service):
    # Mock llm_service.chat_completion
    with patch("app.services.extraction_service.llm_service") as mock_llm:
        mock_llm.chat_completion = AsyncMock(return_value=MOCK_DEEP_ANALYSIS_RESPONSE)
        
        result = await extraction_service.deep_analyze(
            text="I'm not sure if I can do this.",
            character_names=["Hero"],
            audio_features={"pitch": 250, "energy": 0.05, "duration": 2.0},
            emotion_data={"top_emotion": "fear", "emotions": {"fear": 0.8}}
        )
        
        # Verify result structure
        assert "markdown_report" in result
        assert result["markdown_report"] == MOCK_DEEP_ANALYSIS_RESPONSE
        
        assert "structured_data" in result
        data = result["structured_data"]
        assert data["summary"] == "The user is expressing doubt."
        assert len(data["characters"]) == 1
        assert data["characters"][0]["name"] == "Hero"
        assert data["characters"][0]["emotion"] == "Anxious"

@pytest.mark.asyncio
async def test_summarize_session_segment(extraction_service):
    # Mock database session and objects
    mock_db = MagicMock()
    
    # Mock DialogueLog objects
    mock_log1 = MagicMock()
    mock_log1.user_input = "Hi"
    mock_log1.bot_response = "Hello"
    mock_log2 = MagicMock()
    mock_log2.user_input = "How are you?"
    mock_log2.bot_response = "I am fine."
    
    # Setup query chain: db.query().filter().order_by().limit().all()
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_order = mock_filter.order_by.return_value
    mock_limit = mock_order.limit.return_value
    mock_limit.all.return_value = [mock_log2, mock_log1] # Reverse order as in code (descending)
    
    # Mock LLM and Knowledge Service
    with patch("app.services.extraction_service.llm_service") as mock_llm, \
         patch("app.services.extraction_service.knowledge_service") as mock_knowledge:
        
        mock_llm.chat_completion = AsyncMock(return_value="This is a summary.")
        mock_knowledge.add_knowledge = MagicMock()
        
        await extraction_service.summarize_session_segment(mock_db, "session_123")
        
        # Verify LLM called
        mock_llm.chat_completion.assert_called_once()
        
        # Verify Knowledge Indexing called
        mock_knowledge.add_knowledge.assert_called_once()
        args, kwargs = mock_knowledge.add_knowledge.call_args
        assert args[1] == "This is a summary." # text content
        assert args[2]["type"] == "summary" # metadata
