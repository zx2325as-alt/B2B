import math
from collections import Counter
import re

class SimpleBM25:
    """
    A simple implementation of BM25 algorithm for keyword-based retrieval.
    Suitable for small to medium sized datasets where we can hold the index in memory.
    """
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.documents = {} # doc_id -> list of tokens
        self.doc_lengths = {} # doc_id -> int
        self.avg_doc_len = 0
        self.term_doc_freqs = {} # term -> int (number of docs containing term)
        self.total_docs = 0
        self.idf = {}

    def _tokenize(self, text):
        # Simple tokenization: Chinese char or English word
        # For Chinese, ideally use jieba, but we'll use a simple regex for mixed
        # Match Chinese chars or English words
        tokens = re.findall(r'[\u4e00-\u9fa5]|[a-zA-Z0-9]+', text.lower())
        return tokens

    def add_document(self, doc_id, text):
        tokens = self._tokenize(text)
        
        # If updating, we should ideally remove old stats, but for simplicity we assume add/upsert
        # In a real system, we'd need to handle updates more carefully.
        # Here we just overwrite.
        if doc_id in self.documents:
            self._remove_document(doc_id)
            
        self.documents[doc_id] = tokens
        length = len(tokens)
        self.doc_lengths[doc_id] = length
        self.total_docs += 1
        
        # Update term freqs
        unique_tokens = set(tokens)
        for token in unique_tokens:
            self.term_doc_freqs[token] = self.term_doc_freqs.get(token, 0) + 1
            
        self._update_avg_len()
        
    def _remove_document(self, doc_id):
        if doc_id not in self.documents:
            return
            
        tokens = self.documents[doc_id]
        unique_tokens = set(tokens)
        for token in unique_tokens:
            if token in self.term_doc_freqs:
                self.term_doc_freqs[token] -= 1
                if self.term_doc_freqs[token] <= 0:
                    del self.term_doc_freqs[token]
                    
        del self.documents[doc_id]
        del self.doc_lengths[doc_id]
        self.total_docs -= 1
        self._update_avg_len()

    def _update_avg_len(self):
        if self.total_docs > 0:
            self.avg_doc_len = sum(self.doc_lengths.values()) / self.total_docs
        else:
            self.avg_doc_len = 0

    def _compute_idf(self):
        # Compute IDF for all terms
        self.idf = {}
        for term, freq in self.term_doc_freqs.items():
            # Standard IDF formula
            idf = math.log(1 + (self.total_docs - freq + 0.5) / (freq + 0.5))
            self.idf[term] = max(0, idf) # Floor at 0

    def search(self, query, top_k=3):
        if not self.documents:
            return []
            
        self._compute_idf() # Recompute IDF before search (lazy update)
        
        query_tokens = self._tokenize(query)
        scores = {} # doc_id -> score
        
        for doc_id, doc_tokens in self.documents.items():
            score = 0
            doc_len = self.doc_lengths[doc_id]
            doc_token_counts = Counter(doc_tokens)
            
            for token in query_tokens:
                if token not in self.documents[doc_id]:
                    continue
                    
                tf = doc_token_counts[token]
                idf = self.idf.get(token, 0)
                
                # BM25 formula
                numerator = idf * tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
                score += numerator / denominator
                
            if score > 0:
                scores[doc_id] = score
                
        # Sort by score
        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_docs[:top_k]
