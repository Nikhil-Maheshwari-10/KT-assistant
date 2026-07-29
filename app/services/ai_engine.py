import litellm
from litellm import Router
from fastembed import TextEmbedding
from app.core.config import settings
from app.core.logger import logger
from app.models.schemas import Session, Topic, TopicKnowledge
from typing import List, Dict, Optional
import json
import time

class AIEngine:
    def __init__(self):
        self.primary_model = settings.PRIMARY_MODEL_NAME
        self.secondary_model = settings.SECONDARY_MODEL_NAME
        self.tertiary_model = settings.TERTIARY_MODEL_NAME

        # Initialize LiteLLM Router for API Key rotation
        api_keys = [k.strip() for k in settings.GEMINI_API_KEYS.split(",") if k.strip()]
        model_list = []
        for key in api_keys:
            model_list.extend([
                {"model_name": self.primary_model, "litellm_params": {"model": self.primary_model, "api_key": key}},
                {"model_name": self.secondary_model, "litellm_params": {"model": self.secondary_model, "api_key": key}},
                {"model_name": self.tertiary_model, "litellm_params": {"model": self.tertiary_model, "api_key": key}}
            ])
        
        # If no keys provided in .env, fallback to empty to avoid crashing on startup (will fail on generation though)
        if not model_list:
            logger.warning("No GEMINI_API_KEYS found in .env! Generation will fail.")
            
        self.router = Router(
            model_list=model_list, 
            num_retries=settings.LLM_ROUTER_NUM_RETRIES,
            allowed_fails=settings.LLM_ROUTER_ALLOWED_FAILS
        )

        logger.info(f"Loading embedding model ({settings.EMBEDDING_MODEL}) via FastEmbed...")
        self.embedding_model = TextEmbedding(
            model_name=settings.EMBEDDING_MODEL, 
            cache_dir=settings.EMBEDDING_CACHE_DIR
        )

    def get_completion(self, messages: List[Dict], response_format: Optional[Dict] = None, model: Optional[str] = None, call_delay: float = 0.5) -> Optional[str]:
        target_model = model or self.primary_model
        max_retries = settings.LLM_MAX_RETRIES
        retry_delay = settings.LLM_RETRY_DELAY_SECONDS

        for attempt in range(max_retries):
            try:
                import time
                # Protective delay to respect RPM — reduced for lightweight calls
                time.sleep(call_delay)
                
                response = self.router.completion(
                    model=target_model,
                    messages=messages,
                    response_format=response_format,
                    # api_key parameter is now handled internally by self.router
                )
                
                # Log usage and API key used
                usage = getattr(response, 'usage', None)
                used_key_str = ""
                
                if hasattr(response, '_hidden_params') and isinstance(response._hidden_params, dict):
                    used_key = response._hidden_params.get("api_key")
                    if used_key:
                        api_keys = [k.strip() for k in settings.GEMINI_API_KEYS.split(",") if k.strip()]
                        try:
                            idx = api_keys.index(used_key) + 1
                            suffix = "th"
                            if idx == 1: suffix = "st"
                            elif idx == 2: suffix = "nd"
                            elif idx == 3: suffix = "rd"
                            used_key_str = f" [Key: {idx}{suffix}]"
                        except ValueError:
                            pass

                if usage:
                    prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                    completion_tokens = getattr(usage, 'completion_tokens', 0)
                    total_tokens = getattr(usage, 'total_tokens', 0)
                    logger.info(
                        f"LLM Call Success: {target_model}{used_key_str} | "
                        f"Input: {prompt_tokens} | Output: {completion_tokens} | Total: {total_tokens}"
                    )

                return response.choices[0].message.content

            except (litellm.ServiceUnavailableError, litellm.RateLimitError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Gemini busy/limited (Attempt {attempt + 1}). Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2 # Exponential backoff
                else:
                    logger.error(f"Gemini final failure after {max_retries} attempts: {e}")
                    return None
            except Exception as e:
                logger.error(f"Unexpected LiteLLM error: {e}")
                return None
        
        return None

    def get_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * settings.EMBEDDING_DIM
        try:
            t0 = time.time()
            result = list(self.embedding_model.embed([text]))[0].tolist()
            elapsed = time.time() - t0
            logger.debug(f"Embedding generated in {elapsed:.3f}s | Text length: {len(text)} chars")
            return result
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [0.0] * settings.EMBEDDING_DIM

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            t0 = time.time()
            embeddings = list(self.embedding_model.embed(texts))
            elapsed = time.time() - t0
            result = [emb.tolist() for emb in embeddings]
            logger.info(f"Batch embedding complete | {len(texts)} texts embedded in {elapsed:.2f}s ({elapsed/len(texts)*1000:.1f}ms each)")
            return result
        except Exception as e:
            logger.error(f"Batch embedding error: {e}")
            return [[0.0] * settings.EMBEDDING_DIM for _ in texts]

    def classify_intent(self, question: str) -> List[str]:
        """
        Classifies a question into one or more retrieval intents using a fast LLM call.
        Uses a reduced call_delay (0.1s) since the prompt is tiny and cheap.

        Intents:
          STRUCTURAL   — file lists, folder structure, what files exist
          CONTENT      — specific code, logic, config values, function details
          ARCHITECTURE — system design, component relationships, data flow, design patterns
          OPERATIONAL  — deployment, setup, env vars, how to run
          BROAD        — general overview, quality assessment, flaws, comparisons, opinions
        """
        prompt = f"""Classify this technical question into one or more categories (return as comma-separated list):

- STRUCTURAL: asks about files, folders, project structure, what files exist, directory layout
- CONTENT: asks about specific code logic, implementation details, configuration values, function behavior
- ARCHITECTURE: asks about system design, how components connect, data flow, design patterns, tech stack choices
- OPERATIONAL: asks about deployment, running the app, environment setup, installation, docker, CI/CD, how-to steps
- BROAD: asks for a general overview, quality assessment, flaws/weaknesses, best practices, opinions about the system

Question: "{question}"

Return ONLY the category name(s) separated by commas. Examples: "CONTENT" or "STRUCTURAL,CONTENT"
"""
        messages = [
            {"role": "system", "content": "You are a question classifier. Return only category name(s) from the list."},
            {"role": "user", "content": prompt}
        ]
        # Use minimal delay — tiny prompt, very low rate-limit risk
        response = self.get_completion(messages, model=self.secondary_model, call_delay=0.1)
        if not response:
            return ["CONTENT"]

        valid = {"STRUCTURAL", "CONTENT", "ARCHITECTURE", "OPERATIONAL", "BROAD"}
        intents = [i.strip().upper() for i in response.split(",")]
        result = [i for i in intents if i in valid]
        logger.debug(f"Intent raw response: '{response.strip()}'")
        logger.info(f"Intent classified: {result} for question: '{question[:60]}'")
        return result or ["CONTENT"]

    def _build_context(self, question: str, intents: List[str], session, session_id: str, file_manifest: List[str], vector_service) -> tuple:
        """
        Builds the context string for Q&A based on classified intents.
        Returns (context_parts: List[str], final_intents: List[str])

        Fix 1 (CONTENT):      Uses score_threshold=0.4 for dynamic relevance instead of fixed top-5.
        Fix 2 (ARCHITECTURE): New dedicated handler pulling architecture topic + vector search.
        Fix 3 (OPERATIONAL):  Combines ops summary with a supplemental vector search for config files.
        Fix 4 (BROAD):        Combines all topic summaries with a supplemental vector search.
        """
        context_parts = []

        if "STRUCTURAL" in intents:
            if file_manifest:
                # Filter out the internal __REPO__ tag before showing files
                visible_files = [f for f in file_manifest if not f.startswith('__REPO__:')]
                file_list = "\n".join(f"  - {f}" for f in visible_files)
                context_parts.append(f"## Project File Structure ({len(visible_files)} files)\n{file_list}")
            else:
                context_parts.append("## Project File Structure\n(No file manifest available yet.)")

        if "CONTENT" in intents:
            # Use a permissive score_threshold so short/vague questions still get results.
            query_embedding = self.get_embedding(question)
            chunks = vector_service.search_chunks(session_id, query_embedding, limit=settings.RAG_CONTEXT_SIZE, score_threshold=settings.RAG_THRESHOLD_CONTENT)
            if chunks:
                chunk_context = "\n\n---\n\n".join(
                    f"[{c.get('file_path', 'unknown')}]\n{c.get('content', '')}" for c in chunks
                )
                context_parts.append(f"## Relevant Code & File Content\n{chunk_context}")

        if "ARCHITECTURE" in intents:
            # FIX 2: Brand new dedicated handler for architecture questions.
            # Pulls both the structured architecture topic summary AND does a vector search
            # for design patterns and component-level code.
            arch_topic = next((t for t in session.topics if any(
                kw in t.name for kw in ["Architecture", "System", "Design", "Overview"]
            )), None)
            if arch_topic and arch_topic.knowledge:
                context_parts.append(
                    f"## System Architecture Knowledge\n"
                    f"{arch_topic.knowledge.model_dump_json(by_alias=True)}"
                )
            # Supplemental vector search for architecture-level code evidence
            query_embedding = self.get_embedding(question)
            arch_chunks = vector_service.search_chunks(session_id, query_embedding, limit=settings.RAG_CONTEXT_SIZE, score_threshold=settings.RAG_THRESHOLD_CONTENT)
            if arch_chunks:
                arch_chunk_context = "\n\n---\n\n".join(
                    f"[{c.get('file_path', 'unknown')}]\n{c.get('content', '')}" for c in arch_chunks
                )
                context_parts.append(f"## Architecture Evidence (Source Code)\n{arch_chunk_context}")

        if "OPERATIONAL" in intents:
            # FIX 3: Combine the ops topic summary with a supplemental vector search
            # targeting actual config/deployment files (docker, Makefile, CI/CD, env).
            ops_topic = next((t for t in session.topics if "Operation" in t.name), None)
            if ops_topic and ops_topic.knowledge:
                context_parts.append(
                    f"## Operations & Reliability Knowledge\n"
                    f"{ops_topic.knowledge.model_dump_json(by_alias=True)}"
                )
            # Supplemental search for actual raw deployment artifacts
            ops_embedding = self.get_embedding(question + " deploy docker setup environment installation")
            ops_chunks = vector_service.search_chunks(session_id, ops_embedding, limit=settings.RAG_CONTEXT_SIZE, score_threshold=settings.RAG_THRESHOLD_OPERATIONAL)
            if ops_chunks:
                ops_chunk_context = "\n\n---\n\n".join(
                    f"[{c.get('file_path', 'unknown')}]\n{c.get('content', '')}" for c in ops_chunks
                )
                context_parts.append(f"## Operational Config & Script Files\n{ops_chunk_context}")

        if "BROAD" in intents:
            # FIX 4: Combine all topic summaries with a supplemental vector search.
            # This ensures BROAD queries (e.g. "flaws", "weaknesses") also retrieve
            # supporting evidence from raw code (TODO comments, error handling gaps, etc.)
            all_topics = "\n".join(
                f"### {t.name}\n{t.knowledge.model_dump_json(by_alias=True)}" for t in session.topics
            )
            context_parts.append(f"## Full System Knowledge\n{all_topics}")
            # Supplemental vector search to find supporting raw-code evidence
            query_embedding = self.get_embedding(question)
            broad_chunks = vector_service.search_chunks(session_id, query_embedding, limit=settings.RAG_CONTEXT_SIZE, score_threshold=settings.RAG_THRESHOLD_BROAD)
            if broad_chunks:
                broad_chunk_context = "\n\n---\n\n".join(
                    f"[{c.get('file_path', 'unknown')}]\n{c.get('content', '')}" for c in broad_chunks
                )
                context_parts.append(f"## Supporting Code Evidence\n{broad_chunk_context}")

        # Fallback: no score threshold — always return the top results to guarantee context.
        if not context_parts:
            logger.warning("No context gathered — falling back to CONTENT chunk search (no threshold).")
            query_embedding = self.get_embedding(question)
            chunks = vector_service.search_chunks(session_id, query_embedding, limit=settings.RAG_CONTEXT_SIZE)
            if chunks:
                chunk_context = "\n\n---\n\n".join(
                    f"[{c.get('file_path', 'unknown')}]\n{c.get('content', '')}" for c in chunks
                )
                context_parts.append(f"## Relevant Content (fallback)\n{chunk_context}")
                intents = ["CONTENT"]

        logger.info(
            f"Context built | Intents: {intents} | Sources: {len(context_parts)} section(s) | "
            f"Total context chars: {sum(len(p) for p in context_parts)}"
        )
        return context_parts, intents

    def route_and_stream(
        self,
        question: str,
        session,
        session_id: str,
        file_manifest: List[str],
        vector_service,
        intents: List[str] = None,
        history: List[dict] = None,
    ) -> tuple:
        """
        Routes the question to the correct data source(s) based on classified intent,
        then streams the answer token-by-token.
        Returns: (intents: List[str], token_generator)

        The token_generator is a Python generator that yields str tokens.
        Accepts pre-classified intents to avoid a duplicate LLM call.
        Accepts conversation history to resolve pronouns like 'that file', 'it', etc.
        """
        import time
        if intents is None:
            intents = self.classify_intent(question)
        context_parts, intents = self._build_context(question, intents, session, session_id, file_manifest, vector_service)

        if not context_parts:
            def _no_context():
                yield "I don't have enough information to answer that. Please upload a GitHub repository or document first."
            return intents, _no_context()

        full_context = "\n\n".join(context_parts)
        system_prompt = f"""You are a technical Q&A assistant for a software project.
You have access to two sources of information:
1. **Context**: Code snippets and file contents retrieved from the codebase.
2. **Conversation History**: Your previous messages with the user.

Answer the user's question using the Context and Conversation History.
Be specific and concise. Reference file names or sections where helpful.
If an answer spans multiple sources, explain each clearly.
If the answer cannot be found in the Context or Conversation History, say: "This specific detail is not available in the uploaded content."

## Context
{full_context}"""

        # Build the messages list with full conversation history so the LLM can
        # resolve pronouns and follow-up references (e.g. 'that file', 'explain it').
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        def _token_stream():
            stream_start = time.time()
            token_count = 0
            logger.info(f"Stream started | Model: {self.secondary_model} | Session: {session_id} | Intents: {intents}")
            try:
                response = self.router.completion(
                    model=self.secondary_model,
                    messages=messages,
                    stream=True,
                )
                for chunk in response:
                    token = chunk.choices[0].delta.content
                    if token:
                        token_count += 1
                        yield token
                elapsed = time.time() - stream_start
                logger.info(f"Stream complete | {token_count} tokens in {elapsed:.2f}s | Session: {session_id}")
            except litellm.RateLimitError as e:
                import re
                logger.error(f"All API keys rate limited: {e}")
                
                # Extract suggested retry delay for logging purposes
                suggested = re.search(r'retry.*?(\d+(?:\.\d+)?)s', str(e), re.IGNORECASE)
                if suggested:
                    wait_time = min(int(float(suggested.group(1))) + 1, settings.LLM_MAX_RETRY_WAIT_SECONDS)
                    logger.warning(f"All API keys exhausted. Google suggests waiting {wait_time}s.")
                
                yield "\n\n_(Chat is currently busy. Please try again after some time.)_"
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                yield "\n\n_(Error generating response. Please try again later.)_"

        return intents, _token_stream()

    def multi_topic_validate_and_score(self, session: Session, user_message: str) -> Dict[str, Dict]:
        """
        Analyzes the ingested content (GitHub repo or document text) across all topics.
        Returns a dictionary mapping topic_id to its updated coverage results.
        """
        topics_json = {t.id: {"name": t.name, "current_knowledge": t.knowledge.model_dump()} for t in session.topics}
        
        prompt = f"""
        Analyze the following input in the context of a Knowledge Transfer (KT) session.
        The input may contain information relevant to multiple topics at once.
        
        Input: "{user_message}"
        
        Topics and their current accumulated knowledge:
        {json.dumps(topics_json, indent=2)}
        
        Task:
        1. For each topic, extract ALL new information from the input — both for the standard fields AND
           any system-specific details that don't fit the standard fields.
        2. Update the knowledge state for each topic, merging new info with existing knowledge.
        3. For system-specific knowledge that doesn't fit standard fields (e.g., ML pipeline steps,
           API contracts, custom business logic), add them to the "free_form" dict with descriptive keys.
        4. Rate the coverage score (0-100) for each topic based on total knowledge gathered.
        5. List which standard sections are still missing or vague.
        
        Return as a JSON object with topic IDs as keys:
        {{
            "t1": {{
                "knowledge": {{
                    "definition": "...",
                    "purpose": "...",
                    "inputs / outputs": "...",
                    "dependencies": "...",
                    "failure_cases": "...",
                    "edge_cases": "...",
                    "operational_steps": "...",
                    "monitoring / deployment": "...",
                    "free_form": {{
                        "Custom Section Name": "Detailed content here..."
                    }}
                }},
                "confidence_score": 0,
                "missing_sections": ["list of still-missing standard fields"]
            }},
            ...
        }}
        """
        
        messages = [
            {"role": "system", "content": "You are a specialized system analyzer. Always return valid JSON mapping topic IDs to their full updated knowledge state."},
            {"role": "user", "content": prompt}
        ]
        
        response_str = self.get_completion(messages, response_format={"type": "json_object"}, model=self.primary_model)
        if not response_str:
            return {}
            
        try:
            return json.loads(response_str)
        except Exception as e:
            logger.error(f"Error parsing multi-topic validation JSON: {e}")
            return {}

    def _format_knowledge_readable(self, topic_name: str, knowledge) -> str:
        """
        Renders a TopicKnowledge object as clean, readable markdown prose
        instead of a raw JSON blob — helps the LLM reason better.
        """
        field_labels = {
            "definition": "Definition",
            "purpose": "Purpose",
            "inputs_outputs": "Inputs & Outputs",
            "dependencies": "Dependencies",
            "failure_cases": "Failure Cases",
            "edge_cases": "Edge Cases",
            "operational_steps": "Operational Steps",
            "monitoring_deployment": "Monitoring & Deployment",
        }
        lines = [f"### {topic_name}\n"]
        for field, label in field_labels.items():
            value = getattr(knowledge, field, None)
            if value:
                lines.append(f"**{label}:**\n{value}\n")
        # Append any free-form system-specific sections
        if knowledge.free_form:
            for section_name, content in knowledge.free_form.items():
                if content:
                    lines.append(f"**{section_name}:**\n{content}\n")
        return "\n".join(lines)

    def generate_final_summary(self, session: Session) -> str:
        """
        Generates a rich, professional KT document with diagrams, tables, and code snippets.
        Document structure is derived from what was actually learned — not a fixed template.
        """
        system_prompt = f"""
        You are a Senior Technical Architect writing an EXHAUSTIVE, deeply detailed KT (Knowledge Transfer) handover document.
        You will receive structured knowledge extracted from a real codebase.
        
        CRITICAL INSTRUCTION: Do NOT summarize briefly. You must explain every concept thoroughly and deeply as if onboarding a completely new junior engineer who knows nothing about the project. Expand on every single point, provide rich context, and leave no detail unexplained. The document should be lengthy, highly descriptive, and fully comprehensive.

        ## Content Requirements

        Produce a RICH, HIGHLY DETAILED document that includes ALL of the following where data is available:

        1. **Executive Summary** — A deep dive into what the system does, its core business value, target audience, and why it was built.

        2. **Architecture Diagram** — MANDATORY if any architecture info is present.
           Use a Mermaid `graph TD` or `graph LR` diagram to show the high-level components and their relationships.
           STRICT RULES to prevent rendering failures:
           - Always double-quote ALL node labels: `A["My Label"]`, never `A[My Label]`
           - DO NOT use `subgraph` blocks — they break the renderer
           - Keep the diagram simple: maximum 12 nodes
           - Use only `-->` for edges; no `-.->` or `==>`
           Example:
           ```mermaid
           graph TD
               A["Client"] --> B["API Gateway"]
               B --> C["Service A"]
               B --> D["Service B"]
               C --> E["Database"]
           ```

        3. **Data Flow / Sequence Diagram** — MANDATORY if inputs/outputs or request flows are present.
           Use a Mermaid `sequenceDiagram` to show the end-to-end request/data flow.
           Example:
           ```mermaid
           sequenceDiagram
               participant User
               participant API
               participant DB
               User->>API: POST /request
               API->>DB: Query
               DB-->>API: Result
               API-->>User: Response
           ```

        4. **Component / Module Breakdown** — AN EXHAUSTIVE, deeply descriptive breakdown of every major component:
           - Explain EXACTLY what it does, the logic behind it, and why it was built this way.
           - Detail all key classes, functions, and files. Explain how they interact.
           - Describe the tech stack, libraries, and design patterns used.
           - Leave no ambiguity for a new engineer.

        5. **Dependencies Table** — MANDATORY. Markdown table:
           | Dependency | Version | Purpose | Critical? |
           |---|---|---|---|

        6. **Environment Variables Table** — MANDATORY if any config/env info is present:
           | Variable | Required | Default | Description |
           |---|---|---|---|

        7. **API Endpoints Table** — if any API info is present:
           | Method | Endpoint | Auth | Description |
           |---|---|---|---|

        8. **Failure Modes & Recovery Table** — MANDATORY:
           | Failure Scenario | Impact | Detection | Recovery Steps |
           |---|---|---|---|

        9. **Risk Matrix** — MANDATORY:
           | Risk | Likelihood | Impact | Mitigation |
           |---|---|---|---|

        10. **Deployment & Operations** — step-by-step, use numbered lists and code blocks:
            ```bash
            # Example
            docker-compose up -d
            ```

        11. **Monitoring & Alerting** — what metrics/logs/alerts exist.

        12. **Operational Checklist** — MANDATORY. Markdown table:
            | Task | Owner | Priority | Notes |
            |---|---|---|---|

        ## Formatting Rules
        - Use GitHub Flavored Markdown (GFM) ONLY — absolutely NO HTML tags.
        - `#` for document title, `##` for major sections, `###` for subsections.
        - Bold key terms, use inline `code` for variable names, file paths, commands.
        - STRICT LIST FORMATTING: Always use actual line breaks before and after lists. Never put bullets (`*`, `-`) or numbered list items (`1.`) inline within a paragraph. They MUST be on their own lines.
        - MERMAID SYNTAX: Always wrap Mermaid node labels in double quotes to prevent syntax errors with special characters. Example: `A["Client (Web)"] --> B["API Gateway"]`.
        - Use fenced code blocks with language tags for all code and diagrams.
        - ONLY include sections where actual data exists — never pad with generic content.
        - Do NOT invent details not present in the source knowledge.
        - Do NOT include the Session ID or any internal identifiers.
        - Coverage threshold was {settings.KT_CONFIDENCE_THRESHOLD}% — content below that threshold may be incomplete.
        """
        
        # Format each topic as readable markdown prose — not raw JSON
        context_sections = []
        for topic in session.topics:
            context_sections.append(
                self._format_knowledge_readable(topic.name, topic.knowledge)
            )
        context = "\n\n---\n\n".join(context_sections)
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate the final KT document from the following knowledge:\n\n{context}"}
        ]
        
        response = self.get_completion(messages, model=self.primary_model)
        if not response:
            return "Error: Could not generate the final document due to model unavailability. Please try again in 5 minutes."
        
        return self._fix_markdown_formatting(response)

    def _fix_markdown_formatting(self, text: str) -> str:
        """
        Post-processes LLM-generated markdown to fix common formatting issues:
        - Moves inline bullet points (* - ) onto their own line
        - Ensures a blank line precedes list blocks for proper rendering
        - Normalises excessive blank lines
        """
        import re

        # 1. Split inline bullets: when "* " or "- " appears mid-sentence after a space
        #    (catches patterns like "...some text. * **Bold:** ..." → breaks onto new line)
        text = re.sub(r'(?<=[^\n]) (\* )', r'\n* ', text)
        text = re.sub(r'(?<=[^\n]) (- )', r'\n- ', text)

        # 2. Ensure there is a blank line BEFORE each new list line
        #    (Markdown renderers need a blank line before a list starts)
        text = re.sub(r'([^\n])(\n[*\-] )', r'\1\n\2', text)

        # 3. Collapse 3+ consecutive blank lines down to 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()



ai_engine = AIEngine()
