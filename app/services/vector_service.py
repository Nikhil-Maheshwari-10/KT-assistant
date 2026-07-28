
from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.core.config import settings
from app.core.logger import logger
from typing import List, Dict, Optional
import uuid

class VectorService:
    def __init__(self):
        try:
            if settings.QDRANT_URL:
                self.client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY
                )
                logger.info("Connected to Qdrant")
                self._ensure_collection()
            else:
                self.client = None
                logger.warning("QDRANT_URL not provided, vector search disabled")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            self.client = None

    def _ensure_collection(self, collection_name: str = None):
        if not self.client:
            return
        
        if collection_name is None:
            collection_name = settings.QDRANT_COLLECTION
        
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == collection_name for c in collections)
            
            if not exists:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: {collection_name}")
            
            # Ensure payload indexes exist (required for filtering in search)
            if hasattr(self.client, "create_payload_index"):
                for field in ("session_id", "type"):
                    self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD
                    )
        except Exception as e:
            logger.error(f"Error ensuring Qdrant collection or index: {e}")

    def ensure_memory_collection(self):
        """
        Creates the dedicated conversation memory collection if it doesn't exist.
        Uses a 1-dimension dummy vector since memory is payload-based, not vector-search-based.
        Each session gets ONE point whose payload contains all its conversation summaries.
        """
        if not self.client:
            return
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == settings.MEMORY_COLLECTION for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=settings.MEMORY_COLLECTION,
                    vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
                )
                logger.info(f"Created memory collection: {settings.MEMORY_COLLECTION}")
        except Exception as e:
            logger.error(f"Error ensuring memory collection: {e}")

    def upsert_memory_point(self, point_id: str, payload: dict) -> None:
        """Upsert the conversation memory payload for a session (one point per session)."""
        if not self.client:
            return
        try:
            self.client.upsert(
                collection_name=settings.MEMORY_COLLECTION,
                points=[models.PointStruct(id=point_id, vector=[1.0], payload=payload)]
            )
        except Exception as e:
            logger.error(f"Error upserting memory point {point_id}: {e}")

    def get_memory_point(self, point_id: str) -> dict:
        """Retrieve the conversation memory payload for a session."""
        if not self.client:
            return {}
        try:
            results = self.client.retrieve(
                collection_name=settings.MEMORY_COLLECTION,
                ids=[point_id],
                with_payload=True,
            )
            if results:
                return results[0].payload or {}
            return {}
        except Exception as e:
            logger.error(f"Error retrieving memory point {point_id}: {e}")
            return {}

    def delete_memory_point(self, point_id: str) -> None:
        """Delete conversation memory for a session."""
        if not self.client:
            return
        try:
            self.client.delete(
                collection_name=settings.MEMORY_COLLECTION,
                points_selector=models.PointIdsList(points=[point_id])
            )
        except Exception as e:
            logger.error(f"Error deleting memory point {point_id}: {e}")

    def upsert_topic_summary(self, session_id: str, topic_name: str, summary: str, embedding: List[float]):
        if not self.client:
            return

        try:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{session_id}_{topic_name}"))
            
            if not hasattr(self.client, "upsert"):
                logger.error(f"QdrantClient missing 'upsert' method. Cannot index topic: {topic_name}")
                return

            self.client.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "session_id": session_id,
                            "topic": topic_name,
                            "summary": summary
                        }
                    )
                ]
            )
            logger.info(f"Topic '{topic_name}' successfully indexed in Qdrant (Session: {session_id})")
        except Exception as e:
            logger.error(f"Error upserting to Qdrant: {e}")

    def upsert_content_chunks(self, session_id: str, chunks: List[Dict], embeddings: List[List[float]]):
        """
        Stores raw content chunks (from GitHub/file upload) into Qdrant for RAG Q&A.
        Each chunk has type='content_chunk' to distinguish it from topic summaries.
        """
        if not self.client or not chunks:
            return

        points = []
        for chunk, embedding in zip(chunks, embeddings):
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"{session_id}_chunk_{chunk['file_path']}_{chunk['chunk_index']}"
            ))
            points.append(models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "session_id": session_id,
                    "type": "content_chunk",
                    "file_path": chunk["file_path"],
                    "content": chunk["content"],
                    "chunk_index": chunk["chunk_index"],
                }
            ))

        try:
            # Batch upsert in groups of 50 to avoid request size limits
            batch_size = 50
            for i in range(0, len(points), batch_size):
                self.client.upsert(
                    collection_name=settings.QDRANT_COLLECTION,
                    points=points[i:i + batch_size]
                )
            logger.info(f"Indexed {len(points)} content chunks for session {session_id}")
        except Exception as e:
            logger.error(f"Error upserting content chunks to Qdrant: {e}")

    def search_chunks(self, session_id: str, query_embedding: List[float], limit: int = 5, score_threshold: float = None) -> List[Dict]:
        """
        Semantic search over content chunks scoped strictly to the current session.
        Returns list of chunk payloads ordered by relevance.

        Args:
            limit: Maximum number of chunks to return.
            score_threshold: If set, only returns chunks with a cosine similarity score
                             above this value. This gives dynamic result counts instead
                             of a rigid top-N cutoff.
        """
        if not self.client:
            return []

        chunk_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="session_id",
                    match=models.MatchValue(value=session_id)
                ),
                models.FieldCondition(
                    key="type",
                    match=models.MatchValue(value="content_chunk")
                )
            ]
        )

        try:
            if hasattr(self.client, "query_points"):
                kwargs = dict(
                    collection_name=settings.QDRANT_COLLECTION,
                    query=query_embedding,
                    query_filter=chunk_filter,
                    limit=limit,
                )
                if score_threshold is not None:
                    kwargs["score_threshold"] = score_threshold
                results = self.client.query_points(**kwargs).points
                return [hit.payload for hit in results]
            elif hasattr(self.client, "search"):
                kwargs = dict(
                    collection_name=settings.QDRANT_COLLECTION,
                    query_vector=query_embedding,
                    query_filter=chunk_filter,
                    limit=limit,
                )
                if score_threshold is not None:
                    kwargs["score_threshold"] = score_threshold
                results = self.client.search(**kwargs)
                return [hit.payload for hit in results]
            else:
                logger.error("QdrantClient missing search methods.")
                return []
        except Exception as e:
            logger.error(f"Error searching content chunks in Qdrant: {e}")
            return []


    def delete_session_vectors(self, session_id: str):
        if not self.client:
            return

        try:
            self.client.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="session_id",
                            match=models.MatchValue(value=session_id)
                        )
                    ]
                )
            )
            logger.info(f"Deleted vectors for session {session_id} from Qdrant")
        except Exception as e:
            logger.error(f"Error deleting Qdrant vectors: {e}")
    def cleanup_expired_vectors(self, session_ids: List[str]):
        if not self.client or not session_ids:
            return
        
        try:
            self.client.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="session_id",
                            match=models.MatchAny(any=session_ids)
                        )
                    ]
                )
            )
            logger.info(f"Cleanup: Deleted vectors for {len(session_ids)} sessions from Qdrant")
        except Exception as e:
            logger.error(f"Error cleaning up Qdrant vectors: {e}")
    def purge_zombie_vectors(self, active_ids: List[str]) -> int:
        """
        Deletes all vectors that belong to session IDs NOT in the whitelist.
        Returns the count of deleted points.
        """
        if not self.client:
            return 0
        
        try:
            zombie_filter = models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="session_id",
                        match=models.MatchAny(any=active_ids)
                    )
                ]
            )
            
            # 1. Count how many zombies exist
            count_result = self.client.count(
                collection_name=settings.QDRANT_COLLECTION,
                count_filter=zombie_filter,
                exact=True
            )
            zombie_count = count_result.count

            # 2. Delete them
            if zombie_count > 0:
                self.client.delete(
                    collection_name=settings.QDRANT_COLLECTION,
                    points_selector=zombie_filter
                )
            
            return zombie_count
        except Exception as e:
            logger.error(f"Error purging zombies in Qdrant: {e}")
            return 0

vector_service = VectorService()
