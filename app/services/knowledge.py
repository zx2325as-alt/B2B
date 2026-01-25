try:
    import chromadb
except ImportError:
    chromadb = None

import pickle
import os
from typing import List, Dict, Any
from app.utils.logger import logger
from app.core.config import settings
from app.utils.text_utils import SimpleBM25

class KnowledgeService:
    def __init__(self):
        self.bm25_path = settings.DATA_DIR / "bm25_index.pkl"
        self.bm25 = SimpleBM25()
        
        # Load BM25 Index
        if os.path.exists(self.bm25_path):
            try:
                with open(self.bm25_path, "rb") as f:
                    self.bm25 = pickle.load(f)
                logger.info("Loaded BM25 index.")
            except Exception as e:
                logger.error(f"Failed to load BM25 index: {e}")

        if chromadb:
            # Persistent client
            self.client = chromadb.PersistentClient(path=str(settings.DATA_DIR / "chroma_db"))
            self.collection = self.client.get_or_create_collection(name="btb_knowledge")
        else:
            logger.warning("ChromaDB not installed. Knowledge Service running in mock mode.")
            self.client = None
            self.collection = None

    def _save_bm25(self):
        try:
            with open(self.bm25_path, "wb") as f:
                pickle.dump(self.bm25, f)
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")

    async def add_document(self, doc_id: str, text: str, metadata: dict = None):
        if not self.collection:
            logger.warning("Knowledge base not available.")
            return

        try:
            # 1. Update Vector DB
            self.collection.upsert(
                documents=[text],
                metadatas=[metadata or {}],
                ids=[doc_id]
            )
            
            # 2. Update BM25 Index
            self.bm25.add_document(doc_id, text)
            self._save_bm25()
            
            logger.info(f"Added/Updated document {doc_id} in knowledge base.")
        except Exception as e:
            logger.error(f"Error adding document: {e}")

    async def retrieve(self, query: str, top_k: int = 3, filters: dict = None) -> List[dict]:
        """Semantic Retrieval only (Backward compatibility)"""
        return await self._semantic_search(query, top_k, filters)

    async def _semantic_search(self, query: str, top_k: int = 3, filters: dict = None) -> List[dict]:
        if not self.collection:
            return []
            
        try:
            query_args = {
                "query_texts": [query],
                "n_results": top_k
            }
            if filters:
                query_args["where"] = filters
                
            results = self.collection.query(**query_args)
            
            formatted_results = []
            if results['documents']:
                docs = results['documents'][0]
                metadatas = results['metadatas'][0] if results['metadatas'] else [{}] * len(docs)
                ids = results['ids'][0] if results['ids'] else [""] * len(docs)
                
                for i, doc in enumerate(docs):
                    formatted_results.append({
                        "content": doc,
                        "metadata": metadatas[i],
                        "id": ids[i],
                        "score": 0.0 # Placeholder
                    })
                    
            return formatted_results
        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")
            return []

    async def retrieve_hybrid(self, query: str, top_k: int = 3, filters: dict = None) -> List[dict]:
        """
        Hybrid Retrieval: Semantic + BM25
        """
        if not self.collection:
            return []

        # 1. Semantic Search
        semantic_results = await self._semantic_search(query, top_k, filters)
        
        # 2. BM25 Search
        bm25_candidates = self.bm25.search(query, top_k=top_k) # Returns [(doc_id, score), ...]
        
        # Fetch content for BM25 candidates that are NOT in semantic results
        existing_ids = {r['id'] for r in semantic_results}
        missing_ids = [did for did, score in bm25_candidates if did not in existing_ids]
        
        bm25_results = []
        if missing_ids:
            try:
                # Fetch from Chroma
                # Note: Chroma get accepts ids list
                fetched = self.collection.get(ids=missing_ids)
                if fetched['documents']:
                    for i, doc_id in enumerate(fetched['ids']):
                        # Check if filter matches (manual filtering for BM25 results)
                        # This is a bit complex if filter is complex, but simple eq check works
                        meta = fetched['metadatas'][i] if fetched['metadatas'] else {}
                        
                        # Apply filters manually
                        match = True
                        if filters:
                            for k, v in filters.items():
                                if meta.get(k) != v:
                                    match = False
                                    break
                        if match:
                            bm25_results.append({
                                "content": fetched['documents'][i],
                                "metadata": meta,
                                "id": doc_id,
                                "source": "bm25"
                            })
            except Exception as e:
                logger.error(f"Error fetching BM25 docs: {e}")

        # 3. Merge results
        # Simple strategy: Interleave or append
        # Here we just append BM25 results to Semantic results
        final_results = semantic_results + bm25_results
        
        # Dedup is already handled by missing_ids check, but let's be safe
        unique_results = []
        seen_ids = set()
        for r in final_results:
            if r['id'] not in seen_ids:
                unique_results.append(r)
                seen_ids.add(r['id'])
                
        return unique_results[:top_k*2] # Return expanded set

    async def add_dialogue_log(self, log):
        """
        Add a dialogue log to the vector database for semantic retrieval.
        Args:
            log: DialogueLog object (or dict-like)
        """
        if not self.collection:
            return

        try:
            # Construct text representation
            text = f"User: {log.user_input}\nBot: {log.bot_response}"
            
            # Construct metadata
            metadata = {
                "type": "dialogue_log",
                "session_id": str(log.session_id),
                "character_id": str(log.character_id) if log.character_id else "none",
                "timestamp": str(log.created_at) if hasattr(log, 'created_at') else ""
            }
            
            # Use log ID as vector ID
            doc_id = f"log_{log.id}"
            
            # Update both
            self.collection.upsert(
                documents=[text],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            self.bm25.add_document(doc_id, text)
            self._save_bm25()
            
            logger.info(f"Indexed dialogue log {doc_id}")
        except Exception as e:
            logger.error(f"Error indexing dialogue log: {e}")

knowledge_service = KnowledgeService()
