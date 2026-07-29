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
    GEMINI_API_KEYS: str = ""                # Comma separated list of API keys for rotation
    PRIMARY_MODEL_NAME: str 
    SECONDARY_MODEL_NAME: str 
    TERTIARY_MODEL_NAME: str 
    EMBEDDING_MODEL: str 

    # LLM Retry & Rate-Limit Configuration
    LLM_MAX_RETRIES: int = 3                 # Max attempts before giving up on a completion call
    LLM_RETRY_DELAY_SECONDS: int = 2         # Initial backoff delay (doubles each attempt)
    LLM_ROUTER_NUM_RETRIES: int = 2          # Router-level retries across different API keys
    LLM_ROUTER_ALLOWED_FAILS: int = 1        # Failures before a key is temporarily cooled down
    LLM_DEFAULT_CALL_DELAY: float = 0.5      # Default sleep before each LLM call to respect RPM
    LLM_MAX_RETRY_WAIT_SECONDS: int = 90     # Cap on the wait time extracted from Google's retry-after hint

    # App Settings
    LOG_LEVEL: str = "INFO"
    KT_CONFIDENCE_THRESHOLD: int = 80
    CHAT_TIMEOUT_SECONDS: int = 180          # Max seconds for a single chat SSE stream
    INGEST_TIMEOUT_SECONDS: int = 600        # Max seconds for a full repo ingest (large repos are slow)
    INGEST_MAX_CONCURRENCY: int = 3          # Max simultaneous ingest operations (semaphore limit)
    SESSION_EXPIRY_HOURS: int = 6            # Hours after which idle sessions are auto-deleted on startup

    # Embedding & RAG Configuration
    EMBEDDING_DIM: int = 384
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    RAG_CONTEXT_SIZE: int = 8                # Max chunks per vector search (score_threshold filters dynamically)
    QDRANT_COLLECTION: str
    QDRANT_UPSERT_BATCH_SIZE: int = 50       # Points per batch when upserting to Qdrant

    # Memory Configuration
    MEMORY_COLLECTION: str = "KT_ConversationMemory"
    MEMORY_MAX_TURNS: int = 10
    MEMORY_CONSOLIDATION_THRESHOLD: int = 8
    MEMORY_BUFFER_TURNS: int = 2
    EMBEDDING_CACHE_DIR: str = "./model_cache"

    # RAG Score Thresholds (cosine similarity; 0.0=unrelated, 1.0=identical)
    # Lower = more permissive (returns more chunks). Raise if answers are noisy.
    
    RAG_THRESHOLD_CONTENT: float = 0.2       # CONTENT and ARCHITECTURE intents
    RAG_THRESHOLD_OPERATIONAL: float = 0.15  # OPERATIONAL intent (deployment/config files)
    RAG_THRESHOLD_BROAD: float = 0.15        # BROAD intent (general overviews)

    # GitHub ingestion limits
    MAX_TOTAL_CHARS: int = 1_000_000
    MAX_FILE_BYTES: int = 100_000
    MAX_FILES: int = 300
    MAX_CHUNKS: int = 1000
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
