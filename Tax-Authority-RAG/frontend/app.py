import streamlit as st
import requests
import json
import os
import re

st.set_page_config(page_title="IntelliDocs", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for Dark Aurora / Glassmorphism
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700&family=Space+Grotesk:wght@400;500;600;700&display=swap');

    /* Variables */
    :root {
        --bg-main: #0a0a0f;
        --panel-bg: #12121a;
        --accent-cyan: #22d3ee;
        --accent-mint: #34d399;
        --text-primary: #f8fafc;
        --text-secondary: #94a3b8;
        --glass-border: rgba(255, 255, 255, 0.08);
    }

    /* Base Typography & Background */
    .stApp {
        background-color: var(--bg-main);
        background-image: 
            radial-gradient(circle at 10% 20%, rgba(34, 211, 238, 0.15), transparent 40%),
            radial-gradient(circle at 90% 80%, rgba(52, 211, 153, 0.1), transparent 40%);
        background-attachment: fixed;
        font-family: 'DM Sans', sans-serif;
        color: var(--text-primary);
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: 'Space Grotesk', sans-serif !important;
        color: var(--text-primary) !important;
    }

    /* Hide standard header */
    [data-testid="stHeader"] { display: none; }
    .block-container { padding-top: 2rem !important; }

    /* Sidebar Glassmorphism */
    [data-testid="stSidebar"] {
        background-color: rgba(18, 18, 26, 0.6) !important;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-right: 1px solid var(--glass-border);
        width: 260px !important;
    }
    
    /* Logo Area */
    .sidebar-logo {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--glass-border);
    }
    .logo-square {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        background: linear-gradient(135deg, var(--accent-cyan), var(--accent-mint));
    }
    .logo-text {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.2rem;
        font-weight: 600;
        letter-spacing: -0.5px;
    }

    /* Custom File Upload Dropzone */
    [data-testid="stFileUploadDropzone"] {
        background-color: transparent !important;
        border: 2px dashed rgba(255, 255, 255, 0.2) !important;
        border-radius: 12px !important;
        padding: 2rem 1rem !important;
    }
    [data-testid="stFileUploadDropzone"]:hover {
        border-color: var(--accent-cyan) !important;
        background-color: rgba(34, 211, 238, 0.05) !important;
    }
    [data-testid="stFileUploadDropzone"] div {
        color: var(--text-secondary);
    }

    /* Native Tabs Restyling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 500;
        font-size: 1rem;
        color: var(--text-secondary);
    }
    .stTabs [aria-selected="true"] {
        color: var(--text-primary) !important;
        border-bottom-color: transparent !important;
        background: linear-gradient(90deg, var(--accent-cyan), var(--accent-mint));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .stTabs [data-baseweb="tab-highlight"] {
        background: linear-gradient(90deg, var(--accent-cyan), var(--accent-mint)) !important;
        height: 3px;
        border-radius: 3px 3px 0 0;
    }

    /* Chat Messages Glass Panel */
    .stChatMessage {
        background: rgba(18, 18, 26, 0.7);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid var(--glass-border);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    }
    
    /* Sparkle icon style for assistant */
    .stChatMessage.assistant-msg [data-testid="stChatMessageAvatar"] {
        background: transparent;
    }

    /* Prompt Bar */
    [data-testid="stChatInput"] {
        background: rgba(18, 18, 26, 0.8) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 24px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }
    [data-testid="stChatInput"] textarea {
        color: var(--text-primary) !important;
        font-family: 'DM Sans', sans-serif;
    }
    
    /* Highlighted numbers */
    .highlight-mint {
        color: var(--accent-mint);
        font-weight: 600;
    }

    /* Tag buttons */
    .tag-button {
        display: inline-block;
        background: rgba(255,255,255,0.05);
        border: 1px solid var(--glass-border);
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-right: 8px;
        margin-top: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    .tag-button:hover {
        background: rgba(255,255,255,0.1);
        color: var(--text-primary);
        border-color: rgba(255,255,255,0.2);
    }
    
    /* Hero section */
    .hero-container {
        text-align: center;
        padding: 6rem 2rem;
        max-width: 800px;
        margin: 0 auto;
    }
    .hero-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 3.5rem;
        font-weight: 600;
        line-height: 1.1;
        margin-bottom: 1.5rem;
        background: linear-gradient(135deg, #fff, #94a3b8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -1px;
    }
    .hero-subtitle {
        font-family: 'DM Sans', sans-serif;
        font-size: 1.2rem;
        color: var(--text-secondary);
        font-weight: 400;
    }

    /* Small sidebar list item styling */
    .sidebar-doc-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 8px;
        cursor: pointer;
        margin-bottom: 4px;
    }
    .sidebar-doc-item:hover {
        background: rgba(255,255,255,0.05);
    }
    .sidebar-doc-icon {
        color: var(--accent-cyan);
        font-size: 1.2rem;
    }
    .sidebar-doc-details {
        display: flex;
        flex-direction: column;
    }
    .sidebar-doc-name {
        font-size: 0.9rem;
        color: var(--text-primary);
        font-weight: 500;
    }
    .sidebar-doc-pages {
        font-size: 0.75rem;
        color: var(--text-secondary);
    }

</style>
""", unsafe_allow_html=True)

API_URL = os.getenv("API_URL", "http://localhost:8000")

def get_relevance_label(index: int) -> str:
    if index == 0:
        return "🔴 High relevance"
    elif index <= 2:
        return "🟡 Medium relevance"
    else:
        return "🟢 Low relevance"

def fetch_documents():
    try:
        res = requests.get(f"{API_URL}/documents")
        if res.status_code == 200:
            return res.json().get("documents", [])
    except:
        pass
    return []

docs_data = fetch_documents()
docs_names = [d["name"] for d in docs_data]
collections = list(set([d.get("collection") for d in docs_data if d.get("collection")]))

# Initialize session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# SIDEBAR
with st.sidebar:
    # Logo Area
    st.markdown("""
        <div class="sidebar-logo">
            <div class="logo-square"></div>
            <div class="logo-text">IntelliDocs</div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<h3 style='font-size: 0.9rem; color: #94a3b8; margin-top: 1rem;'>Library</h3>", unsafe_allow_html=True)
    
    if docs_data:
        for doc in docs_data:
            pages = doc.get('pages', '?')
            st.markdown(f"""
                <div class="sidebar-doc-item">
                    <span class="sidebar-doc-icon">📄</span>
                    <div class="sidebar-doc-details">
                        <span class="sidebar-doc-name">{doc['name']}</span>
                        <span class="sidebar-doc-pages">{pages} pages</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.write("No documents uploaded yet.")
        
    st.markdown("<br><h3 style='font-size: 0.9rem; color: #94a3b8;'>Collections</h3>", unsafe_allow_html=True)
    
    if collections:
        for coll in collections:
            st.markdown(f"""
                <div class="sidebar-doc-item">
                    <span class="sidebar-doc-icon">📁</span>
                    <div class="sidebar-doc-details">
                        <span class="sidebar-doc-name">{coll}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.write("No collections available.")

    st.markdown("<br><br>", unsafe_allow_html=True)
    
    # Dropzone
    uploaded_file = st.file_uploader("Drop files here", type=["pdf"])
    if st.button("Upload"):
        if uploaded_file is not None:
            with st.spinner("Uploading..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                try:
                    res = requests.post(f"{API_URL}/upload", files=files)
                    if res.status_code == 200:
                        st.success(f"Uploaded successfully!")
                        st.rerun()
                    else:
                        st.error(f"Upload failed: {res.text}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

# MAIN WORKSPACE
# Header Tabs
tab_chat, tab_summarize, tab_compare, tab_insights = st.tabs(["Chat", "Summarize", "Compare", "Insights"])

with tab_chat:
    col1, col2 = st.columns([4, 1])
    with col2:
        # Scope Dropdown
        search_scope = st.selectbox("Scope", ["All Documents", "Current View", "Selected (3)"], label_visibility="collapsed")
    
    st.markdown("<br>", unsafe_allow_html=True)

    if not st.session_state.messages:
        # Hero Section
        st.markdown("""
            <div class="hero-container">
                <h1 class="hero-title">Synthesize knowledge from your document library.</h1>
                <p class="hero-subtitle">Select a document to begin analysis or ask a specific question across your entire repository.</p>
            </div>
        """, unsafe_allow_html=True)

    # Chat Interface
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="✨"):
                st.markdown(msg["content"], unsafe_allow_html=True)
                if "sources" in msg and msg["sources"]:
                    with st.expander("Sources / Citations"):
                        for i, source in enumerate(msg["sources"]):
                            st.markdown(f"**{get_relevance_label(i)}** - Document: `{source['document_name']}`, Page: `{source['page_number']}`")
                            st.info(source["text"])
                if "details" in msg and msg["details"]:
                    st.caption(f"⏱️ {msg['details'].get('latency_seconds', 0):.2f}s | 🎯 {msg['details'].get('retrieval_details', {}).get('chunks_retrieved', 0)} chunks | 📄 {', '.join(msg['details'].get('retrieval_details', {}).get('documents_hit', []))}")


    if prompt := st.chat_input("Ask about your documents... ⌘K"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()

    # Generate response
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        prompt = st.session_state.messages[-1]["content"]
        with st.chat_message("assistant", avatar="✨"):
            with st.spinner("Searching and generating answer..."):
                try:
                    # Special hardcoded response for the exact prompt as requested by user
                    if "liquidity requirements" in prompt.lower() and "q4 report" in prompt.lower():
                        answer = """
                        The liquidity requirements in the Q4 report are currently <span class="highlight-mint">$4.2M</span> (up 12% from <span class="highlight-mint">$3.75M</span> in Q3 projections).
                        
                        - **Operational Reserves**: Increased to support new product lines.
                        - **Regulatory Buffers**: Adjusted to meet updated compliance standards.
                        
                        <div style="margin-top: 15px;">
                            <span class="tag-button">Reference Doc #12</span>
                            <span class="tag-button">Explain Calculation</span>
                        </div>
                        """
                        st.markdown(answer, unsafe_allow_html=True)
                        st.session_state.messages.append({"role": "assistant", "content": answer})
                    else:
                        # Normal API call
                        history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1] if "content" in m and not m["content"].startswith("<")]
                        payload = {
                            "query": prompt,
                            "history": history,
                            "search_scope": "all",
                            "search_target": None
                        }
                        res = requests.post(f"{API_URL}/ask", json=payload)
                        if res.status_code == 200:
                            data = res.json()
                            answer = data.get("answer", "")
                            citations = data.get("citations", [])
                            
                            # highlight $ amounts optionally?
                            # For now just use standard answer
                            st.markdown(answer)
                            if citations:
                                with st.expander("Sources / Citations"):
                                    for i, source in enumerate(citations):
                                        st.markdown(f"**{get_relevance_label(i)}** - Document: `{source['document_name']}`, Page: `{source['page_number']}`")
                                        st.info(source["text"])
                            
                            details = {
                                "latency_seconds": data.get("latency_seconds"),
                                "retrieval_details": data.get("retrieval_details")
                            }
                            st.caption(f"⏱️ {details['latency_seconds']:.2f}s | 🎯 {details['retrieval_details'].get('chunks_retrieved')} chunks | 📄 {', '.join(details['retrieval_details'].get('documents_hit', []))}")
                            
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": answer,
                                "sources": citations,
                                "details": details
                            })
                        else:
                            st.error(f"Error: {res.text}")
                except Exception as e:
                    st.error(f"API Connection error: {e}")

with tab_summarize:
    st.subheader("Document Summarization")
    if docs_names:
        doc_to_sum = st.selectbox("Select document to summarize", docs_names, key="sum_doc")
        if st.button("Generate Summary"):
            with st.spinner("Analyzing document..."):
                try:
                    res = requests.post(f"{API_URL}/summarize", json={"document_name": doc_to_sum})
                    if res.status_code == 200:
                        st.markdown(res.json().get("summary", ""))
                    else:
                        st.error(f"Failed: {res.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        st.info("Upload a document first.")

with tab_compare:
    st.subheader("Compare Documents")
    if len(docs_names) >= 2:
        col1, col2 = st.columns(2)
        with col1:
            doc1 = st.selectbox("Document 1", docs_names, key="comp_doc1")
        with col2:
            doc2 = st.selectbox("Document 2", [d for d in docs_names if d != doc1], key="comp_doc2")
            
        comp_query = st.text_input("Comparison Topic / Question", "What are the key differences?")
        
        if st.button("Compare"):
            with st.spinner("Comparing documents..."):
                try:
                    res = requests.post(f"{API_URL}/compare", json={"query": comp_query, "doc1": doc1, "doc2": doc2})
                    if res.status_code == 200:
                        st.markdown(res.json().get("comparison", ""))
                    else:
                        st.error(f"Failed: {res.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        st.info("Upload at least two documents to use this feature.")

with tab_insights:
    st.subheader("System Insights")
    try:
        res = requests.get(f"{API_URL}/insights")
        if res.status_code == 200:
            data = res.json()
            col1, col2 = st.columns(2)
            col1.metric("Documents Indexed", data.get("documents_indexed", 0))
            col2.metric("Knowledge Chunks Processed", data.get("chunks_processed", 0))
    except:
        st.error("Could not load insights.")
