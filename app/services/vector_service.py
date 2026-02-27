
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
            
            # Ensure payload index for session_id exists (required for deletion filters)
            if hasattr(self.client, "create_payload_index"):
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name="session_id",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
        except Exception as e:
            logger.error(f"Error ensuring Qdrant collection or index: {e}")

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

    def search_kt(self, query_embedding: List[float], limit: int = 5) -> List[Dict]:
        if not self.client:
            return []

        try:
            # Try newer query_points API first (v1.10+) or fallback to search
            if hasattr(self.client, "query_points"):
                results = self.client.query_points(
                    collection_name=settings.QDRANT_COLLECTION,
                    query=query_embedding,
                    limit=limit
                ).points
                return [hit.payload for hit in results]
            elif hasattr(self.client, "search"):
                results = self.client.search(
                    collection_name=settings.QDRANT_COLLECTION,
                    query_vector=query_embedding,
                    limit=limit
                )
                return [hit.payload for hit in results]
            else:
                available_methods = [m for m in dir(self.client) if not m.startswith("_")]
                logger.error(f"QdrantClient missing 'search' and 'query_points' methods. Available: {available_methods}")
                return []
        except Exception as e:
            logger.error(f"Error searching Qdrant: {e}")
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
