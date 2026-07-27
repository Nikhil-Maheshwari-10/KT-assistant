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
    GEMINI_API_KEY: Optional[str] = None
    PRIMARY_MODEL_NAME: str
    SECONDARY_MODEL_NAME: str
    EMBEDDING_MODEL: str
    
    # App Settings
    LOG_LEVEL: str = "INFO"
    KT_CONFIDENCE_THRESHOLD: int = 80
    CHAT_TIMEOUT_SECONDS: int = 180      # Max seconds for a single chat SSE stream
    INGEST_TIMEOUT_SECONDS: int = 600    # Max seconds for a full repo ingest (large repos are slow)
    
    # Embedding & RAG Configuration
    EMBEDDING_DIM: int = 3072
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    RAG_CONTEXT_SIZE: int = 5
    QDRANT_COLLECTION: str
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
