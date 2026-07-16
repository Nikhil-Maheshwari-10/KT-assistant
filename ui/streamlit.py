import streamlit as st
import uuid
import sys
import os
import json

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app.core.config import settings
from app.core.logger import logger
from app.models.schemas import Session, Topic, Message, TopicKnowledge
from app.services.db_service import db_service
from app.services.ai_engine import ai_engine
from app.services.vector_service import vector_service
from app.services.doc_processor import extract_text_from_file, chunk_text
from app.services.github_service import fetch_repo_content

st.set_page_config(page_title="KT Assistant", layout="wide", initial_sidebar_state="expanded")

def process_knowledge(text: str):
    """Processes technical knowledge across all topics and updates the session state."""
    all_results = ai_engine.multi_topic_validate_and_score(st.session_state.session, text)
    
    for topic in st.session_state.session.topics:
        if topic.id in all_results:
            data = all_results[topic.id]
            old_score = topic.confidence_score
            topic.knowledge = TopicKnowledge(**data.get("knowledge", {}))
            topic.confidence_score = data.get("confidence_score", 0)
            topic.missing_sections = data.get("missing_sections", [])
            
            if topic.confidence_score != old_score:
                logger.info(f"Topic '{topic.name}' updated. Confidence: {old_score}% -> {topic.confidence_score}%")

            if topic.confidence_score >= settings.KT_CONFIDENCE_THRESHOLD:
                if not topic.is_complete:
                    topic.is_complete = True
                    # Index to Vector DB (RAG Prep)
                    summary_text = json.dumps(topic.knowledge.model_dump(), indent=2)
                    embedding = ai_engine.get_embedding(f"Topic: {topic.name}\nContent: {summary_text}")
                    vector_service.upsert_topic_summary(
                        st.session_state.session_id, 
                        topic.name, 
                        summary_text, 
                        embedding
                    )
    
    st.session_state.session.overall_confidence = int(sum(t.confidence_score for t in st.session_state.session.topics) / len(st.session_state.session.topics))
    db_service.save_session(st.session_state.session)


def index_chunks(chunks: list):
    """Embeds and indexes raw content chunks into Qdrant for Q&A RAG."""
    if not chunks:
        return
    texts = [c["content"] for c in chunks]
    with st.spinner(f"Indexing {len(chunks)} content chunks for Q&A..."):
        embeddings = ai_engine.get_embeddings_batch(texts)
        vector_service.upsert_content_chunks(
            st.session_state.session_id, chunks, embeddings
        )
    logger.info(f"Indexed {len(chunks)} chunks for session {st.session_state.session_id}")

# --- View State & Session Logic ---
if "view" not in st.session_state:
    # If a session ID is provided in the URL, go straight to chat
    url_session_id = st.query_params.get("session_id")
    if url_session_id:
        st.session_state.view = "chat"
    else:
        st.session_state.view = "landing"

# --- Automatic Data Cleanup (6 Hour TTL) ---
if "cleanup_done" not in st.session_state:
    with st.spinner("Performing periodic maintenance..."):
        # 1. Expire sessions older than 6 hours
        expired_ids = db_service.cleanup_expired_sessions(hours=6)
        expired_count = len(expired_ids)
        
        # 2. Get whitelist of all remaining active sessions
        active_ids = db_service.get_all_active_session_ids()
        
        # 3. Purge any vectors NOT in the whitelist (Zombies)
        qdrant_deleted_count = vector_service.purge_zombie_vectors(active_ids)
        
        logger.info(f"Healthcheckup done: {expired_count} expired sessions deleted from Supabase and {qdrant_deleted_count} from qdrant")
        st.session_state.cleanup_done = True

# --- Chat Interface Initialization (Only if in chat view) ---
if st.session_state.view == "chat":
    if "session_id" not in st.session_state:
        url_session_id = st.query_params.get("session_id")
        
        if url_session_id:
            # Try to load existing session from Supabase
            existing_session = db_service.get_session(url_session_id)
            if existing_session:
                st.session_state.session_id = url_session_id
                st.session_state.session = existing_session
                st.session_state.chat_history = db_service.get_messages(url_session_id)
                logger.info(f"Loaded existing session from URL: {url_session_id}")
            else:
                # Redirect or start fresh if ID invalid
                st.session_state.session_id = str(uuid.uuid4())
                st.query_params["session_id"] = st.session_state.session_id
                logger.warning(f"URL session {url_session_id} not found. Starting new.")
        else:
            # No ID anywhere - this shouldn't happen with the current button logic 
            # but we handle it for safety
            st.session_state.session_id = str(uuid.uuid4())
            st.query_params["session_id"] = st.session_state.session_id

    # Initialize Session Object & Chat History if still empty
    if "session" not in st.session_state:
        initial_topics = [
            Topic(id="t1", name="System Overview", missing_sections=["definition", "purpose"]),
            Topic(id="t2", name="Architecture & Data Flow", missing_sections=["inputs / outputs", "monitoring / deployment"]),
            Topic(id="t3", name="Operations & Reliability", missing_sections=["failure cases", "edge cases", "operational steps"])
        ]
        st.session_state.session = Session(id=st.session_state.session_id, topics=initial_topics)
        db_service.save_session(st.session_state.session)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
        greeting = Message(role="assistant", content="Hello! I'm your Knowledge Transfer Assistant. Let's start the KT session. Can you give me a high-level overview of the system we're documenting today?")
        st.session_state.chat_history.append(greeting)
        db_service.save_message(st.session_state.session_id, greeting)

if st.session_state.view == "landing":
    st.markdown("""
        <style>
        .stApp {
            background: #0e1117;
        }
        .main-container {
            max-width: 900px;
            margin: 0 auto;
            padding: 4rem 1rem;
            text-align: center;
        }
        .hero-title {
            font-size: 4rem;
            font-weight: 800;
            background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 1.5rem;
            letter-spacing: -1.5px;
        }
        .hero-desc {
            font-size: 1.4rem;
            color: #8892b0;
            line-height: 1.6;
            margin-bottom: 3rem;
        }
        .highlight-box {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 2.5rem;
            margin-bottom: 3rem;
            text-align: left;
        }
        .highlight-item {
            margin-bottom: 1.5rem;
            display: flex;
            align-items: flex-start;
        }
        .highlight-icon {
            font-size: 1.8rem;
            margin-right: 1.2rem;
            margin-top: -4px;
        }
        .highlight-text b {
            color: #4facfe;
            display: block;
            font-size: 1.2rem;
            margin-bottom: 0.2rem;
        }
        .highlight-text p {
            color: #a8b2d1;
            margin: 0;
            font-size: 1.05rem;
        }
        /* Button Styling */
        div.stButton > button {
            background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%) !important;
            color: white !important;
            font-weight: 700 !important;
            padding: 0.8rem 4rem !important;
            border-radius: 50px !important;
            border: none !important;
            transition: all 0.3s ease !important;
            font-size: 1.3rem !important;
            box-shadow: 0 4px 20px rgba(0, 242, 254, 0.4) !important;
        }
        div.stButton > button:hover {
            transform: scale(1.05) !important;
            box-shadow: 0 10px 30px rgba(0, 242, 254, 0.6) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="main-container">', unsafe_allow_html=True)
        st.markdown('<h1 class="hero-title">Knowledge Transfer Assistant</h1>', unsafe_allow_html=True)
        st.markdown('<p class="hero-desc">I am your technical documentation partner. I don\'t just record what you say—I actively interview you to uncover architectural details, operational risks, and system complexities.</p>', unsafe_allow_html=True)
        
        st.markdown("""
            <div class="highlight-box">
                <div class="highlight-item">
                    <span class="highlight-icon">🧠</span>
                    <div class="highlight-text">
                        <b>Active Interrogation</b>
                        <p>I ask probing questions to move beyond basic summaries and capture deep technical nuances.</p>
                    </div>
                </div>
                <div class="highlight-item">
                    <span class="highlight-icon">📊</span>
                    <div class="highlight-text">
                        <b>Coverage Scoring</b>
                        <p>I track progress against key topics like Architecture, Data Flow, and Reliability to ensure zero knowledge gaps.</p>
                    </div>
                </div>
                <div class="highlight-item">
                    <span class="highlight-icon">📄</span>
                    <div class="highlight-text">
                        <b>Structured Artifacts</b>
                        <p>Once complete, I transform our dialogue into a professional technical document ready for your team.</p>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        if st.button("🚀 Start KT Session"):
            # Force create a fresh session
            new_id = str(uuid.uuid4())
            st.session_state.session_id = new_id
            st.query_params["session_id"] = new_id
            logger.info(f"User started a fresh KT session: {new_id}")
            
            # Initialize fresh state
            initial_topics = [
                Topic(id="t1", name="System Overview", missing_sections=["definition", "purpose"]),
                Topic(id="t2", name="Architecture & Data Flow", missing_sections=["inputs / outputs", "monitoring / deployment"]),
                Topic(id="t3", name="Operations & Reliability", missing_sections=["failure cases", "edge cases", "operational steps"])
            ]
            st.session_state.session = Session(id=new_id, topics=initial_topics)
            db_service.save_session(st.session_state.session)
            
            st.session_state.chat_history = []
            greeting = Message(role="assistant", content="Hello! I'm your Knowledge Transfer Assistant. Let's start the KT session. Can you give me a high-level overview of the system we're documenting today?")
            st.session_state.chat_history.append(greeting)
            db_service.save_message(new_id, greeting)
            
            st.session_state.view = "chat"
            st.rerun()
            
        st.markdown('</div>', unsafe_allow_html=True)

else:
    # --- Sidebar ---
    with st.sidebar:
        st.title("KT Assistant")
        
        st.divider()
        
        st.subheader("Progress")
        overall_progress = sum(t.confidence_score for t in st.session_state.session.topics) / len(st.session_state.session.topics)
        st.progress(overall_progress / 100)
        st.write(f"Overall Completeness: {overall_progress:.1f}%")
        
        st.divider()
        
        st.subheader("Topics")
        current_topic_idx = 0
        for i, topic in enumerate(st.session_state.session.topics):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{topic.name}**")
            with col2:
                st.write(f"{topic.confidence_score}%")
            st.progress(topic.confidence_score / 100)
            
            # Determine the current active topic (first one under threshold)
            if topic.confidence_score < settings.KT_CONFIDENCE_THRESHOLD and current_topic_idx == 0:
                current_topic_idx = i

        st.divider()
        
        can_generate = all(t.confidence_score >= settings.KT_CONFIDENCE_THRESHOLD for t in st.session_state.session.topics)
        if st.button("Generate Final Summary", disabled=not can_generate):
            logger.info(f"User triggered final summary generation for session: {st.session_state.session_id}")
            with st.spinner("Generating professional KT document..."):
                summary = ai_engine.generate_final_summary(st.session_state.session)
                
                # Clean HTML tags immediately at generation time
                import re
                clean_summary = re.sub(r'<[^>]+>', '', summary)
                st.session_state.final_summary = clean_summary
                
                # CRITICAL: Clear PDF cache so it regenerates for the download button
                if "pdf_bytes" in st.session_state:
                    del st.session_state["pdf_bytes"]
                    
                st.success("Summary generated!")

        st.divider()
        
        if st.button("Clear Session Data", type="secondary"):
            with st.spinner("Clearing data..."):
                db_service.delete_session_data(st.session_state.session_id)
                vector_service.delete_session_vectors(st.session_state.session_id)
                logger.info(f"Session {st.session_state.session_id} cleared by user")
                
                # Clear URL params and local state
                st.query_params.clear()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()

        st.divider()
        st.subheader("🐙 GitHub Repository")
        github_url = st.text_input(
            "GitHub URL",
            placeholder="https://github.com/owner/repo",
            label_visibility="collapsed",
            key="github_url_input"
        )
        if st.button("🚀 Fetch & Analyse Repo", key="github_fetch_btn", use_container_width=True):
            if not github_url.strip():
                st.warning("Please enter a GitHub repository URL first.")
            else:
                with st.spinner("Fetching repository files from GitHub..."):
                    ingest_result = fetch_repo_content(github_url.strip())

                if not ingest_result.success:
                    st.error(f"❌ {ingest_result.error}")
                else:
                    # Inject a chat message so the history reflects the source
                    repo_msg = Message(
                        role="user",
                        content=(
                            f"🐙 **GitHub Repository Ingested:** `{ingest_result.owner}/{ingest_result.repo}` "
                            f"(branch: `{ingest_result.branch}`) — "
                            f"{len(ingest_result.files_fetched)} files, "
                            f"{ingest_result.total_chars / 1024:.1f} KB processed."
                        )
                    )
                    st.session_state.chat_history.append(repo_msg)
                    db_service.save_message(st.session_state.session_id, repo_msg)

                    # Feed into KT topic scoring pipeline
                    with st.spinner("Analysing repository content across KT topics..."):
                        process_knowledge(ingest_result.aggregated_text)

                    # Index raw chunks into Qdrant for Q&A
                    index_chunks(ingest_result.chunks)

                    # Store file manifest for intent-based routing (STRUCTURAL queries)
                    st.session_state.file_manifest = ingest_result.files_fetched

                    st.success(
                        f"✅ Fetched **{len(ingest_result.files_fetched)} files** "
                        f"({ingest_result.total_chars / 1024:.1f} KB, {len(ingest_result.chunks)} chunks) from "
                        f"`{ingest_result.owner}/{ingest_result.repo}`. "
                        f"Coverage & Q&A ready!"
                    )
                    logger.info(f"GitHub repo ingested: {ingest_result.summary}")
                    st.rerun()

        st.divider()
        st.subheader("📁 Knowledge Upload")
        uploaded_file = st.file_uploader("Upload PDF or TXT", type=["pdf", "txt"], label_visibility="collapsed")
        if uploaded_file:
            if "last_uploaded_file" not in st.session_state or st.session_state.last_uploaded_file != uploaded_file.name:
                with st.spinner(f"Processing {uploaded_file.name}..."):
                    file_bytes = uploaded_file.read()
                    text = extract_text_from_file(file_bytes, uploaded_file.name)
                    if text:
                        doc_msg = Message(role="user", content=f"📄 **Uploaded Document:** {uploaded_file.name}")
                        st.session_state.chat_history.append(doc_msg)
                        db_service.save_message(st.session_state.session_id, doc_msg)
                        
                        # KT topic scoring
                        process_knowledge(text)

                        # Index raw chunks for Q&A
                        file_chunks = chunk_text(text, source_name=uploaded_file.name,
                                                  chunk_size=settings.CHUNK_SIZE,
                                                  chunk_overlap=settings.CHUNK_OVERLAP)
                        index_chunks(file_chunks)

                        # Extend file manifest for intent routing
                        existing = st.session_state.get("file_manifest", [])
                        if uploaded_file.name not in existing:
                            st.session_state.file_manifest = existing + [uploaded_file.name]
                        
                        st.session_state.last_uploaded_file = uploaded_file.name
                        st.success(f"✅ Processed {uploaded_file.name} — {len(file_chunks)} chunks indexed for Q&A!")
                        st.rerun()
                    else:
                        st.error("Could not read file content.")

    # --- Main Chat ---
    # Mode toggle
    has_chunks = any(t.confidence_score > 0 for t in st.session_state.session.topics)

    col_title, col_toggle = st.columns([3, 2])
    with col_title:
        st.header("KT Assistant Chat")
    with col_toggle:
        chat_mode = st.radio(
            "Chat Mode",
            options=["💬 Q&A", "📥 Add Knowledge"],
            horizontal=True,
            key="chat_mode_radio",
            label_visibility="collapsed",
        )

    # Mode hint
    if chat_mode == "💬 Q&A":
        if has_chunks:
            st.caption("Ask any question about the uploaded project — answers come from the actual files.")
        else:
            st.info("📂 Upload a GitHub repository or document via the sidebar to enable Q&A.")
    else:
        st.caption("Tell the assistant more about the system to improve coverage scores.")

    # Display chat messages
    for message in st.session_state.chat_history:
        with st.chat_message(message.role):
            st.markdown(message.content)

    # --- Q&A Mode ---
    if chat_mode == "💬 Q&A":
        placeholder = "Ask anything about the uploaded project..."
        if prompt := st.chat_input(placeholder, disabled=not has_chunks):
            user_msg = Message(role="user", content=prompt)
            st.session_state.chat_history.append(user_msg)
            db_service.save_message(st.session_state.session_id, user_msg)
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                # Phase 1: classify intent + fetch context (interactive status)
                with st.status("Analyzing question...", expanded=True) as status:
                    intents, token_stream = ai_engine.route_and_stream(
                        question=prompt,
                        session=st.session_state.session,
                        session_id=st.session_state.session_id,
                        file_manifest=st.session_state.get("file_manifest", []),
                        vector_service=vector_service,
                    )
                    
                    intent_labels = {
                        "STRUCTURAL": "📁 file structure",
                        "CONTENT": "🔍 code search",
                        "OPERATIONAL": "⚙️ ops knowledge",
                        "BROAD": "🌐 full overview",
                    }
                    sources = " + ".join(intent_labels.get(i, i) for i in intents)
                    status.update(label=f"Sourced via: {sources}", state="complete", expanded=False)

                # Phase 2: stream the answer token-by-token
                answer = st.write_stream(token_stream)

                ai_msg = Message(role="assistant", content=answer)
                st.session_state.chat_history.append(ai_msg)
                db_service.save_message(st.session_state.session_id, ai_msg)
                st.rerun()

    # --- Add Knowledge Mode ---
    else:
        placeholder = "Tell me more about the system..."
        if prompt := st.chat_input(placeholder):
            user_msg = Message(role="user", content=prompt)
            st.session_state.chat_history.append(user_msg)
            db_service.save_message(st.session_state.session_id, user_msg)
            with st.chat_message("user"):
                st.markdown(prompt)

            # Update topic knowledge
            with st.spinner("Analyzing response..."):
                process_knowledge(prompt)

            # AI follow-up question
            active_topic = st.session_state.session.topics[current_topic_idx]
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    if active_topic.is_complete and current_topic_idx + 1 < len(st.session_state.session.topics):
                        next_topic = st.session_state.session.topics[current_topic_idx + 1]
                        response = f"Great! I have a solid understanding of '{active_topic.name}'. Let's move to '{next_topic.name}'. "
                        response += ai_engine.interrogate(st.session_state.session, st.session_state.chat_history, next_topic)
                    elif all(t.is_complete for t in st.session_state.session.topics):
                        response = "I have gathered all the necessary information. The KT session is complete! You can now generate the final summary from the sidebar."
                    else:
                        response = ai_engine.interrogate(st.session_state.session, st.session_state.chat_history, active_topic)

                    st.markdown(response)
                    ai_msg = Message(role="assistant", content=response)
                    st.session_state.chat_history.append(ai_msg)
                    db_service.save_message(st.session_state.session_id, ai_msg)
                    st.rerun()

    # --- Display Summary if generated ---
    if "final_summary" in st.session_state:
        st.divider()
        st.subheader("Final KT Document")
        st.markdown(st.session_state.final_summary)
        
        # Generate PDF if not already in session state
        if "pdf_bytes" not in st.session_state:
            from markdown_pdf import MarkdownPdf, Section
            import tempfile
            
            try:
                # Strictly B&W CSS for technical PDF (No gray tones)
                pdf_css = """
                body { font-family: 'Helvetica', sans-serif; line-height: 1.6; color: #000; margin: 40px; background-color: #fff; }
                h1 { color: #000; border-bottom: 2px solid #000; padding-bottom: 10px; font-size: 24px; }
                h2 { color: #000; margin-top: 25px; border-bottom: 1px solid #000; font-size: 20px; }
                h3 { color: #000; margin-top: 20px; font-size: 16px; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 10pt; }
                th, td { border: 1px solid #000; padding: 8px; text-align: left; background-color: #fff; }
                th { color: #000; font-weight: bold; border-bottom: 2px solid #000; }
                tr { background-color: #fff; }
                code { background-color: #fff; padding: 2px 4px; border: 1px solid #000; border-radius: 4px; font-family: monospace; font-size: 9pt; }
                pre { background-color: #fff; padding: 15px; border-radius: 5px; overflow-x: auto; border: 1px solid #000; font-size: 9pt; color: #000; }
                blockquote { border-left: 5px solid #000; padding-left: 15px; margin-left: 0; color: #000; font-style: italic; }
                """
                
                pdf = MarkdownPdf()
                pdf.add_section(Section(st.session_state.final_summary), user_css=pdf_css)
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    pdf.save(tmp.name)
                    with open(tmp.name, "rb") as f:
                        st.session_state.pdf_bytes = f.read()
                    os.unlink(tmp.name)
            except Exception as e:
                logger.error(f"PDF generation failed: {e}")
                st.error("Failed to generate PDF. You can still copy the text above.")

        if "pdf_bytes" in st.session_state:
            st.download_button(
                label="📥 Download as PDF",
                data=st.session_state.pdf_bytes,
                file_name=f"KT_Assistant_Summary_{st.session_state.session_id[:8]}.pdf",
                mime="application/pdf",
                use_container_width=True
            )



