from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

from app.core.logger import logger
from app.core.config import settings
from app.services.db_service import db_service
from app.services.vector_service import vector_service

scheduler = AsyncIOScheduler()

async def run_cleanup():
    """
    Periodic job to clean up expired sessions from Supabase and orphaned vectors from Qdrant.
    """
    logger.info("Running periodic session cleanup...")
    try:
        expired_ids = db_service.cleanup_expired_sessions(hours=settings.SESSION_EXPIRY_HOURS)
        active_ids = db_service.get_all_active_session_ids()
        zombie_count = vector_service.purge_zombie_vectors(active_ids)
        
        logger.info(
            f"Cleanup complete: {len(expired_ids)} expired sessions removed, "
            f"{zombie_count} zombie vectors purged."
        )
    except Exception as e:
        logger.warning(f"Periodic cleanup failed: {e}")

def start_scheduler():
    """Starts the APScheduler with the cleanup job."""
    scheduler.add_job(
        run_cleanup, 
        "interval", 
        hours=settings.SESSION_EXPIRY_HOURS,
        next_run_time=datetime.now()   # Fires immediately on startup
    )
    scheduler.start()
    logger.info(f"APScheduler started: cleanup job scheduled every {settings.SESSION_EXPIRY_HOURS} hours.")

def stop_scheduler():
    """Stops the APScheduler."""
    scheduler.shutdown()
    logger.info("APScheduler stopped.")
