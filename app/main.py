import os
import shutil
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .rag.models import UserContext
from .rag.retrieval import InMemoryOpenSearchBackend
from .rag.ingestion import parse_pdf
from .rag.service import RagService

app = FastAPI(title="IntelliDocs API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Global dependencies
backend = InMemoryOpenSearchBackend(chunks=[])
rag_service = RagService(backend=backend)
default_user = UserContext(user_id="admin", role="admin")

# Document Metadata Store
DOCUMENT_STORE: Dict[str, Dict[str, Any]] = {}

class Message(BaseModel):
    role: str
    content: str

class AskRequest(BaseModel):
    query: str
    history: Optional[List[Message]] = None
    search_scope: Optional[str] = "all"
    search_target: Optional[str] = None

class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    page_number: str
    text: str

class AskResponse(BaseModel):
    query: str
    answer: str
    abstained: bool
    citations: List[CitationOut]
    latency_seconds: float
    retrieval_details: dict

class SummarizeRequest(BaseModel):
    document_name: str

class CompareRequest(BaseModel):
    query: str
    doc1: str
    doc2: str

class CollectionUpdateRequest(BaseModel):
    document_name: str
    collection: Optional[str]

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    file_path = UPLOAD_DIR / file.filename
    try:
        file_size = 0
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_size = os.path.getsize(file_path)
        
        DOCUMENT_STORE[file.filename] = {
            "status": "Processing",
            "pages": 0,
            "size": file_size,
            "collection": None
        }

        chunks = parse_pdf(file_path, document_name=file.filename)
        if not chunks:
            DOCUMENT_STORE[file.filename]["status"] = "Failed"
            raise HTTPException(status_code=400, detail="No text could be extracted from the PDF.")
            
        page_count = max([c.page_number for c in chunks]) if chunks else 0
        DOCUMENT_STORE[file.filename]["pages"] = page_count
        DOCUMENT_STORE[file.filename]["status"] = "Indexing"
        
        try:
            texts = [c.text for c in chunks]
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('all-MiniLM-L6-v2')
            embeddings = model.encode(texts)
            for i, chunk in enumerate(chunks):
                chunk.embedding = embeddings[i].tolist()
                
            backend.add_chunks(chunks)
            DOCUMENT_STORE[file.filename]["status"] = "Ready"
        except Exception as e:
            DOCUMENT_STORE[file.filename]["status"] = "Failed"
            raise HTTPException(status_code=500, detail=f"Failed to embed chunks: {str(e)}")
            
        return {"message": "Document uploaded and processed successfully", "chunks": len(chunks)}
    except Exception as e:
        if file.filename in DOCUMENT_STORE:
            DOCUMENT_STORE[file.filename]["status"] = "Failed"
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
def list_documents():
    docs = set([c.document_name for c in backend.chunks])
    result = []
    for doc in docs:
        meta = DOCUMENT_STORE.get(doc, {"status": "Ready", "pages": 0, "size": 0, "collection": None})
        result.append({
            "name": doc,
            **meta
        })
    return {"documents": result}

@app.delete("/documents/{doc_name}")
def delete_document(doc_name: str):
    if doc_name in DOCUMENT_STORE:
        del DOCUMENT_STORE[doc_name]
    
    original_len = len(backend._chunks)
    backend._chunks = [c for c in backend._chunks if c.document_name != doc_name]
    if len(backend._chunks) == original_len:
        raise HTTPException(status_code=404, detail="Document not found.")
        
    return {"message": "Document deleted"}

@app.post("/collections")
def update_collection(req: CollectionUpdateRequest):
    if req.document_name not in DOCUMENT_STORE:
        if req.document_name in set([c.document_name for c in backend.chunks]):
            DOCUMENT_STORE[req.document_name] = {"status": "Ready", "pages": 0, "size": 0, "collection": None}
        else:
            raise HTTPException(status_code=404, detail="Document not found")
            
    DOCUMENT_STORE[req.document_name]["collection"] = req.collection
    return {"message": "Collection updated"}

@app.get("/insights")
def get_insights():
    total_docs = len(set([c.document_name for c in backend.chunks]))
    total_chunks = len(backend.chunks)
    return {
        "documents_indexed": total_docs,
        "chunks_processed": total_chunks,
    }

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    history_dicts = [m.model_dump() for m in req.history] if req.history else []
    
    document_names = None
    if req.search_scope == "document" and req.search_target:
        document_names = [req.search_target]
    elif req.search_scope == "collection" and req.search_target:
        document_names = [name for name, meta in DOCUMENT_STORE.items() if meta.get("collection") == req.search_target]
        if not document_names:
            document_names = ["__EMPTY_COLLECTION__"]
            
    result = rag_service.ask(default_user, req.query, history=history_dicts, document_names=document_names)
    
    retrieval_details = {
        "chunks_retrieved": len(result.retrieved_chunk_ids),
        "method": "Hybrid (Lexical + Vector + Rerank)",
        "documents_hit": list(set([c["document_name"] for c in result.citations]))
    }
    
    return AskResponse(
        query=result.query,
        answer=result.answer,
        abstained=result.abstained,
        citations=[CitationOut(**c) for c in result.citations],
        latency_seconds=result.latency_seconds,
        retrieval_details=retrieval_details
    )

@app.post("/summarize")
def summarize(req: SummarizeRequest):
    summary = rag_service.summarize_document(default_user, req.document_name)
    return {"summary": summary}

@app.post("/compare")
def compare(req: CompareRequest):
    comparison = rag_service.compare_documents(default_user, req.query, req.doc1, req.doc2)
    return {"comparison": comparison}
