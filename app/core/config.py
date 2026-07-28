from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Supabase Configuration
    SUPABASE_URL: str
    SUPABASE_KEY: str
    
    # Qdrant Configuration
    QDRANT_URL: Optional[str] = None
    QDRANT_API_KEY: Optional[str] = None
    
    # LiteLLM Configuration
    GEMINI_API_KEYS: str = "" # Comma separated list of API keys for rotation
    PRIMARY_MODEL_NAME: str
    SECONDARY_MODEL_NAME: str
    TERTIARY_MODEL_NAME: str
    EMBEDDING_MODEL: str
    
    # App Settings
    LOG_LEVEL: str = "INFO"
    KT_CONFIDENCE_THRESHOLD: int = 80
    CHAT_TIMEOUT_SECONDS: int = 180      # Max seconds for a single chat SSE stream
    INGEST_TIMEOUT_SECONDS: int = 600    # Max seconds for a full repo ingest (large repos are slow)

    # Embedding & RAG Configuration
    EMBEDDING_DIM: int = 384
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    RAG_CONTEXT_SIZE: int = 8            # Max chunks per vector search (score_threshold filters dynamically)
    QDRANT_COLLECTION: str
    MEMORY_COLLECTION: str = "KT_ConversationMemory"  # Dedicated collection for per-session conversation summaries
    MEMORY_MAX_TURNS: int = 10                          # Max turns to inject into LLM context
    MEMORY_CONSOLIDATION_THRESHOLD: int = 8             # Merge history when turn count reaches this
    MEMORY_BUFFER_TURNS: int = 2                        # Number of recent turns to keep separate from consolidation
    EMBEDDING_CACHE_DIR: str = "./model_cache"

    # GitHub ingestion limits (Greatly expanded since embeddings are now free & local)
    MAX_TOTAL_CHARS: int = 1_000_000 # Increased to 1MB of repo data
    MAX_FILE_BYTES: int = 100_000    # Individual files up to 100KB
    MAX_FILES: int = 300             # Max number of files to fetch per repo
    MAX_CHUNKS: int = 1000           # Increased from 150: we can index way more code now!
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
