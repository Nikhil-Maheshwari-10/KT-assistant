"""
app/services/memory_service.py
=============================================================================
                    CONVERSATION MEMORY SERVICE
=============================================================================
Manages per-session conversation memory in Qdrant, following the same
architecture as ai-trading-app's memory_service.py — adapted and simplified
for KT-assistant's shorter, codebase-focused sessions.

Architecture:
  - ONE Qdrant point per session in the KT_ConversationMemory collection.
  - Each point's payload is a list of SummaryTurn dicts:
      { user_query: str, summary: str | None }
  - Point ID is a deterministic UUID derived from session_id.

3-Stage Pipeline:
  1. store_pending_turn()     — called at START of request, stores placeholder with summary=None
  2. retrieve_history()       — called before building LLM context, returns formatted turn history
  3. summarize_and_store()    — called at END of request (background), fills in the summary
=============================================================================
"""
from __future__ import annotations

import hashlib
import time
from typing import List, Optional, Dict, Any

from app.core.config import settings
from app.core.logger import logger
from app.services.vector_service import vector_service


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _session_point_id(session_id: str) -> str:
    """Derive a deterministic UUID-formatted string from session_id (MD5-based)."""
    h = hashlib.md5(session_id.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    """
    Manages per-session conversation memory backed by Qdrant.
    One Qdrant point per session; payload stores a list of SummaryTurn dicts.
    """

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get_payload(self, session_id: str) -> Dict[str, Any]:
        """Fetch the raw session memory payload from Qdrant."""
        point_id = _session_point_id(session_id)
        return vector_service.get_memory_point(point_id)

    def _save_payload(self, session_id: str, payload: Dict[str, Any]) -> None:
        """Upsert the session memory payload to Qdrant."""
        point_id = _session_point_id(session_id)
        vector_service.upsert_memory_point(point_id, payload)

    # ------------------------------------------------------------------
    # Stage 1: Store pending turn immediately (at request start)
    # ------------------------------------------------------------------

    def store_pending_turn(self, session_id: str, user_query: str) -> None:
        """
        Immediately writes a placeholder SummaryTurn with summary=None.

        WHY: If the user asks Q2 while Q1's summary is still being generated
        in a background thread, Q2's history retrieval will still see Q1 as
        a pending entry — so the LLM knows what was recently discussed.
        """
        if not session_id or not user_query:
            return
        try:
            payload = self._get_payload(session_id)
            summaries: List[Dict] = payload.get("summaries", [])

            # Deduplication: don't add the same query twice
            already_pending = any(
                t.get("user_query") == user_query and t.get("summary") is None
                for t in summaries
            )
            if already_pending:
                return

            summaries.append({"user_query": user_query, "summary": None})
            payload["summaries"] = summaries
            payload["session_id"] = session_id
            payload["updated_at"] = time.time()
            self._save_payload(session_id, payload)
            logger.debug(f"[MEMORY] Pending turn stored for session {session_id}")
        except Exception as e:
            logger.error(f"[MEMORY] Failed to store pending turn: {e}")

    # ------------------------------------------------------------------
    # Stage 2: Retrieve history (before building LLM context)
    # ------------------------------------------------------------------

    def retrieve_history(self, session_id: str) -> List[Dict[str, str]]:
        """
        Returns the conversation history as a list of role/content dicts
        compatible with the LLM messages list format.

        Pending turns (summary=None) are included as partial entries so the
        LLM knows the immediately preceding question even if summarization
        hasn't finished yet.

        Returns at most settings.MEMORY_MAX_TURNS recent turns.
        """
        if not session_id:
            return []
        try:
            payload = self._get_payload(session_id)
            summaries: List[Dict] = payload.get("summaries", [])
            if not summaries:
                return []

            # Take the N most recent completed + any pending turns
            # (exclude the very last pending turn — that's the current question)
            turns_for_context = summaries[-(settings.MEMORY_MAX_TURNS + 1):-1]

            history = []
            for i, turn in enumerate(turns_for_context, start=1):
                user_query = turn.get("user_query", "")
                summary = turn.get("summary")
                if not user_query:
                    continue

                history.append({"role": "user", "content": user_query})

                if summary:
                    # Inject the AI's compact summary as the assistant turn
                    history.append({"role": "assistant", "content": summary})
                else:
                    # Pending turn: signal that a response was being generated
                    history.append({"role": "assistant", "content": "[Response being generated...]"})

            logger.debug(f"[MEMORY] Retrieved {len(turns_for_context)} turns for session {session_id}")
            return history
        except Exception as e:
            logger.error(f"[MEMORY] Failed to retrieve history: {e}")
            return []

    # ------------------------------------------------------------------
    # Stage 3: Generate summary and store (at request end, background)
    # ------------------------------------------------------------------

    def summarize_and_store(
        self,
        session_id: str,
        user_query: str,
        ai_response: str,
        ai_engine,
    ) -> None:
        """
        Generates a compact LLM summary of the (query, response) pair and
        updates the matching pending turn in Qdrant.

        Designed to be called in a background thread after the stream completes
        so it doesn't block the SSE response to the client.
        """
        if not session_id or not user_query or not ai_response:
            return
        try:
            # Generate a compact 1-2 sentence summary using a cheap LLM call
            summary_prompt = f"""Summarize this Q&A exchange in 1-2 concise sentences. 
Focus on what was asked and the key factual answer. Be specific about file names, functions, or concepts mentioned.

Question: {user_query}

Answer: {ai_response[:1500]}

Return ONLY the summary, no preamble."""

            messages = [
                {"role": "system", "content": "You are a concise technical summarizer."},
                {"role": "user", "content": summary_prompt}
            ]
            summary = ai_engine.get_completion(messages, model=ai_engine.tertiary_model, call_delay=0.0)
            if not summary:
                summary = f"User asked: {user_query[:100]}"  # fallback

            # Find the matching pending turn and fill in the summary
            payload = self._get_payload(session_id)
            summaries: List[Dict] = payload.get("summaries", [])

            updated = False
            for turn in reversed(summaries):
                if turn.get("user_query") == user_query and turn.get("summary") is None:
                    turn["summary"] = summary.strip()
                    updated = True
                    break

            if not updated:
                # Safeguard: append if pending turn was lost
                summaries.append({"user_query": user_query, "summary": summary.strip()})

            payload["summaries"] = summaries
            payload["updated_at"] = time.time()
            self._save_payload(session_id, payload)
            
            # Check if consolidation is needed
            completed_turns = [t for t in summaries if t.get("summary") is not None]
            logger.info(f"[MEMORY] Summary stored for session {session_id} ({len(completed_turns)} turns total)")

            if len(completed_turns) >= settings.MEMORY_CONSOLIDATION_THRESHOLD:
                import threading
                threading.Thread(
                    target=self.consolidate_session,
                    args=(session_id, ai_engine),
                    daemon=True,
                ).start()

        except Exception as e:
            logger.error(f"[MEMORY] Failed to summarize and store: {e}")

    # ------------------------------------------------------------------
    # Stage 4: Consolidate old history (background task)
    # ------------------------------------------------------------------

    def consolidate_session(self, session_id: str, ai_engine) -> None:
        """
        Merges old history turns into a single milestone summary block
        while leaving the most recent N turns intact.
        """
        import re
        try:
            payload = self._get_payload(session_id)
            summaries: List[Dict] = payload.get("summaries", [])
            completed_turns = [t for t in summaries if t.get("summary") is not None]

            if len(completed_turns) < settings.MEMORY_CONSOLIDATION_THRESHOLD:
                return

            buffer_size = settings.MEMORY_BUFFER_TURNS
            turns_to_consolidate = completed_turns[:-buffer_size]
            all_turn_count = len(summaries)

            if not turns_to_consolidate:
                return

            # Determine base question number from existing consolidated turn
            first_turn = turns_to_consolidate[0]
            base_q = 0
            m = re.search(r"Q-1 to Q-(\d+)", first_turn.get("user_query", ""))
            if m:
                base_q = int(m.group(1))

            new_total = base_q + (len(turns_to_consolidate) - 1) if base_q else len(turns_to_consolidate)
            
            history_text = "\n".join(t.get("summary", "") for t in turns_to_consolidate)
            
            consolidation_prompt = f"""Summarize the following sequence of Q&A interactions into one coherent, factual paragraph.
Preserve all important technical details, file names, and decisions.

{history_text}

Return ONLY the consolidated summary, no preamble."""

            messages = [
                {"role": "system", "content": "You are a technical document summarizer."},
                {"role": "user", "content": consolidation_prompt}
            ]
            
            clean_master = ai_engine.get_completion(messages, model=ai_engine.tertiary_model, call_delay=0.0)
            if not clean_master:
                return

            consolidated_turn = {
                "user_query": f"[CONSOLIDATED HISTORY: Q-1 to Q-{new_total}]",
                "summary": clean_master.strip()
            }

            # Re-fetch payload to avoid race conditions with incoming queries
            fresh_payload = self._get_payload(session_id)
            fresh_summaries = fresh_payload.get("summaries", [])
            
            # Replace the old turns with the single consolidated turn
            new_summaries = [consolidated_turn] + fresh_summaries[all_turn_count - buffer_size:]
            fresh_payload["summaries"] = new_summaries
            fresh_payload["updated_at"] = time.time()
            
            self._save_payload(session_id, fresh_payload)
            logger.info(f"🔄 [MEMORY] Consolidation complete for {session_id}. History compressed to {len(new_summaries)} turns.")

        except Exception as e:
            logger.error(f"❌ [MEMORY] Consolidation failed for {session_id}: {e}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete_session_memory(self, session_id: str) -> None:
        """Delete all conversation memory for a session (called on session delete)."""
        point_id = _session_point_id(session_id)
        vector_service.delete_memory_point(point_id)
        logger.info(f"[MEMORY] Deleted memory for session {session_id}")


# Singleton
memory_service = MemoryService()
