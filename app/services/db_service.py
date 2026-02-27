from supabase import create_client, Client
from app.core.config import settings
from app.core.logger import logger
from app.models.schemas import Session, Topic, Message
from typing import List, Optional
import json

class DBService:
    def __init__(self):
        try:
            self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            logger.info("Connected to Supabase")
        except Exception as e:
            logger.error(f"Failed to connect to Supabase: {e}")
            raise e

    def save_session(self, session: Session):
        try:
            from datetime import datetime
            session.updated_at = datetime.now() # Update timestamp before saving
            data = {
                "id": session.id,
                "overall_confidence": session.overall_confidence,
                "status": session.status,
                "updated_at": session.updated_at.isoformat(),
                "topics": [t.model_dump(by_alias=True) for t in session.topics]
            }
            # upsert session
            self.supabase.table("sessions").upsert(data).execute()
            logger.info(f"Created new session {session.id} and synced to Supabase")
        except Exception as e:
            logger.error(f"Error saving session: {e}")

    def cleanup_expired_sessions(self, hours: int = 6) -> List[str]:
        """
        Deletes sessions that haven't been updated for the specified number of hours.
        Returns a list of session IDs that were deleted.
        """
        try:
            from datetime import datetime, timedelta
            threshold = datetime.now() - timedelta(hours=hours)
            
            # 1. Identify expired sessions
            response = self.supabase.table("sessions").select("id").lt("updated_at", threshold.isoformat()).execute()
            expired_ids = [row["id"] for row in response.data]
            
            if expired_ids:
                # 2. Delete them (Cascades to messages)
                self.supabase.table("sessions").delete().in_("id", expired_ids).execute()
                logger.debug(f"DB Cleanup: Batch deleted {len(expired_ids)} sessions")
            
            return expired_ids
        except Exception as e:
            logger.error(f"Error during Supabase cleanup: {e}")
            return []

    def get_session(self, session_id: str) -> Optional[Session]:
        try:
            response = self.supabase.table("sessions").select("*").eq("id", session_id).execute()
            if response.data:
                data = response.data[0]
                return Session(**data)
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None

    def save_message(self, session_id: str, message: Message):
        try:
            data = {
                "session_id": session_id,
                "role": message.role,
                "content": message.content,
                "metadata": message.metadata
            }
            self.supabase.table("messages").insert(data).execute()
            logger.debug(f"Message saved for session {session_id}")
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    def get_all_active_session_ids(self) -> List[str]:
        try:
            response = self.supabase.table("sessions").select("id").execute()
            return [row["id"] for row in response.data]
        except Exception as e:
            logger.error(f"Error getting active session IDs: {e}")
            return []

    def get_messages(self, session_id: str) -> List[Message]:
        try:
            response = self.supabase.table("messages").select("*").eq("session_id", session_id).order("timestamp").execute()
            return [Message(**m) for m in response.data]
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def delete_session_data(self, session_id: str):
        try:
            # Cascading delete will handle messages if foreign key is set correctly
            # In our SQL script it is: REFERENCES sessions(id) ON DELETE CASCADE
            self.supabase.table("sessions").delete().eq("id", session_id).execute()
            logger.info(f"Deleted data for session {session_id} from Supabase")
        except Exception as e:
            logger.error(f"Error deleting session data: {e}")

db_service = DBService()
