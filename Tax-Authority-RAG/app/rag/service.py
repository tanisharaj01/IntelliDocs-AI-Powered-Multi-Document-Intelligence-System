"""High-level orchestrator for IntelliDocs.

Handles the pipeline: Embed -> Hybrid Retrieve -> Rerank -> LLM Generation.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, List

import os
from google import genai
from sentence_transformers import SentenceTransformer

from .models import Chunk, UserContext, Citation
from .retrieval import RetrievalBackend, hybrid_retrieve


@dataclass
class AskResult:
    user_id: str
    query: str
    answer: str
    abstained: bool
    citations: list[dict[str, str]]
    retrieved_chunk_ids: list[str]
    latency_seconds: float


class RagService:
    def __init__(self, backend: RetrievalBackend) -> None:
        self._backend = backend
        self.embed_model = SentenceTransformer('all-MiniLM-L6-v2')

    @property
    def backend(self) -> RetrievalBackend:
        return self._backend

    def ask(self, user: UserContext, query: str, history: List[dict] = None, document_names: List[str] = None) -> AskResult:
        start = time.perf_counter()

        # We assume GEMINI_API_KEY is available in the environment.
        # If not, this will fail. Streamlit UI will handle that.
        
        # 1. Embed Query
        # We now use the local sentence-transformer model
        try:
            query_embedding = self.embed_model.encode(query).tolist()
        except Exception as e:
            print(f"Embedding failed: {e}")
            query_embedding = [0.0] * 384  # MiniLM-L6-v2 vector dimension

        # 2. Hybrid Retrieval & Reranking
        # We pass a simple mock embedder that returns the pre-computed embedding
        class MockEmbedder:
            def embed(self, text): return query_embedding
            def embed_query(self, text): return query_embedding
        
        retrieved_chunks, debug_info = hybrid_retrieve(
            query=query,
            user=user,
            backend=self._backend,
            embedder=MockEmbedder(),
            lexical_top_k=20,
            vector_top_k=20,
            fused_candidates=30,
            rerank_max=15,
            final_top_n=5,
            document_names=document_names
        )

        # 3. Prompt Construction
        context_str = ""
        for i, chunk in enumerate(retrieved_chunks):
            context_str += f"--- Document: {chunk.document_name} | Page: {chunk.page_number} | ID: {chunk.chunk_id} ---\n"
            context_str += f"{chunk.text}\n\n"

        system_prompt = (
            "You are an AI Document Intelligence Assistant named IntelliDocs.\n"
            "First, try to use the provided context to answer the user's question. "
            "If you use the context, you MUST cite your sources using the format [Document: <doc_name>, Page: <page_number>].\n"
            "If the provided context does not contain the answer, you are authorized and encouraged to use your Google Search tool to search the internet and provide a comprehensive answer. When doing so, mention that you found the information online."
        )

        # Build a single prompt string to pass to Gemini
        prompt_parts = [f"System Instruction: {system_prompt}\n"]
        if history:
            prompt_parts.append("--- Conversation History ---")
            for m in history:
                prompt_parts.append(f"{m['role'].capitalize()}: {m['content']}")
                
        prompt_parts.append("--- Current Request ---")
        prompt_parts.append(f"Context:\n{context_str}\n\nQuestion:\n{query}")
        
        final_prompt = "\n".join(prompt_parts)

        # 4. LLM Generation
        answer_text = ""
        abstained = False
        try:
            client = genai.Client()  # Automatically picks up GEMINI_API_KEY
            chat_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=final_prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    tools=[{"google_search": {}}]
                )
            )
            answer_text = chat_res.text
            
            if "I couldn't find enough information" in answer_text:
                abstained = True
        except Exception as e:
            answer_text = f"Error generating answer with Gemini: {e}"
            abstained = True

        # Extract citations (just attaching all retrieved chunk citations for now as sources)
        citations = []
        for c in retrieved_chunks:
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "document_name": c.document_name,
                "page_number": str(c.page_number),
                "text": c.text,
            })

        elapsed = time.perf_counter() - start
        
        return AskResult(
            user_id=user.user_id,
            query=query,
            answer=answer_text,
            abstained=abstained,
            citations=citations,
            retrieved_chunk_ids=[c.chunk_id for c in retrieved_chunks],
            latency_seconds=elapsed,
        )

    def summarize_document(self, user: UserContext, document_name: str) -> str:
        # Retrieve chunks from the specific document
        chunks = [c for c in self._backend.chunks if c.document_name == document_name]
        
        # Take the first 15 chunks to avoid token limits while getting a good overview
        sorted_chunks = sorted(chunks, key=lambda c: c.page_number)[:15]
        
        if not sorted_chunks:
            return "No content found to summarize."

        context_str = ""
        for chunk in sorted_chunks:
            context_str += f"--- Page: {chunk.page_number} ---\n{chunk.text}\n\n"

        prompt = (
            f"You are an AI Document Intelligence Assistant.\n"
            f"Please provide a comprehensive summary of the document '{document_name}' based on the following excerpts.\n"
            f"Include an Executive Summary, Key Points, Important Figures, and Main Conclusions.\n\n"
            f"Excerpts:\n{context_str}"
        )

        try:
            client = genai.Client()
            chat_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.2)
            )
            return chat_res.text
        except Exception as e:
            return f"Error generating summary: {e}"

    def compare_documents(self, user: UserContext, query: str, doc1: str, doc2: str) -> str:
        # Hybrid retrieve for doc1
        res1, _ = hybrid_retrieve(
            query=query, user=user, backend=self._backend, embedder=self.embed_model,
            lexical_top_k=10, vector_top_k=10, fused_candidates=15, rerank_max=10, final_top_n=5,
            document_names=[doc1]
        )
        
        # Hybrid retrieve for doc2
        res2, _ = hybrid_retrieve(
            query=query, user=user, backend=self._backend, embedder=self.embed_model,
            lexical_top_k=10, vector_top_k=10, fused_candidates=15, rerank_max=10, final_top_n=5,
            document_names=[doc2]
        )
        
        context_str = f"--- {doc1} ---\n"
        for chunk in res1:
            context_str += f"[Page {chunk.page_number}] {chunk.text}\n\n"
            
        context_str += f"\n--- {doc2} ---\n"
        for chunk in res2:
            context_str += f"[Page {chunk.page_number}] {chunk.text}\n\n"

        prompt = (
            f"You are an AI Document Intelligence Assistant.\n"
            f"The user wants to compare two documents based on the following question/topic: '{query}'.\n"
            f"Please generate a structured comparison based ONLY on the following retrieved context.\n"
            f"Where appropriate, output a comparative table. You must cite your sources (e.g. Document Name - Page X) for all important claims.\n\n"
            f"Context:\n{context_str}"
        )

        try:
            client = genai.Client()
            chat_res = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(temperature=0.1)
            )
            return chat_res.text
        except Exception as e:
            return f"Error generating comparison: {e}"
