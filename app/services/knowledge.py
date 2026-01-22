try:
    import chromadb
except ImportError:
    chromadb = None

from typing import List
from app.utils.logger import logger
from app.core.config import settings

class KnowledgeService:
    def __init__(self):
        if chromadb:
            # Persistent client
            self.client = chromadb.PersistentClient(path=str(settings.DATA_DIR / "chroma_db"))
            self.collection = self.client.get_or_create_collection(name="btb_knowledge")
        else:
            logger.warning("ChromaDB not installed. Knowledge Service running in mock mode.")
            self.client = None
            self.collection = None
        
    async def add_document(self, doc_id: str, text: str, metadata: dict = None):
        if not self.collection:
            logger.warning("Knowledge base not available.")
            return

        try:
            self.collection.add(
                documents=[text],
                metadatas=[metadata or {}],
                ids=[doc_id]
            )
            logger.info(f"Added document {doc_id} to knowledge base.")
        except Exception as e:
            logger.error(f"Error adding document: {e}")

    async def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        if not self.collection:
            return []
            
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k
            )
            return results['documents'][0] if results['documents'] else []
        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")
            return []

knowledge_service = KnowledgeService()
