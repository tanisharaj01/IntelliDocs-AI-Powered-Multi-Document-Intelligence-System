"""Document ingestion pipeline for IntelliDocs.

Extracts text from uploaded PDFs page by page, and emits chunks.
Uses PyMuPDF (fitz) for fast and accurate PDF parsing.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import List

import fitz  # PyMuPDF

from .models import Chunk


def _stable_chunk_id(document_id: str, page_number: int, index: int = 0) -> str:
    """Generate a stable chunk ID based on document, page, and chunk index."""
    joined = f"{document_id}::{page_number}::{index}"
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:20]


def parse_pdf(file_path: Path, document_name: str, document_id: str = None) -> List[Chunk]:
    """Parse a single PDF file into chunks (one chunk per page or split further if needed).

    For simplicity, we create one chunk per page. For production, you could 
    further split pages into paragraphs or fixed token sizes.
    """
    if not document_id:
        document_id = str(uuid.uuid4())
        
    chunks: List[Chunk] = []
    
    try:
        # Open the PDF using PyMuPDF
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text").strip()
            
            # Skip empty pages
            if not text:
                continue
                
            # If text is too long, we might want to split it. 
            # For simplicity in this PoC, we take the page as a single chunk.
            # Real-world usage would use a proper text splitter (e.g., RecursiveCharacterTextSplitter)
            
            chunk = Chunk(
                chunk_id=_stable_chunk_id(document_id, page_num + 1),
                document_id=document_id,
                document_name=document_name,
                text=text,
                page_number=page_num + 1,  # 1-indexed pages
            )
            chunks.append(chunk)
            
        doc.close()
    except Exception as e:
        print(f"Error parsing PDF {file_path}: {e}")
        
    return chunks
