from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

class TopicKnowledge(BaseModel):
    definition: Optional[str] = None
    purpose: Optional[str] = None
    inputs_outputs: Optional[str] = Field(None, alias="inputs / outputs")
    dependencies: Optional[str] = None
    failure_cases: Optional[str] = None
    edge_cases: Optional[str] = None
    operational_steps: Optional[str] = None
    monitoring_deployment: Optional[str] = Field(None, alias="monitoring / deployment")

    @field_validator("*", mode="before")
    @classmethod
    def list_to_str(cls, v: Any) -> Any:
        if isinstance(v, list):
            return "\n".join([f"- {item}" for item in v])
        return v

class Topic(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    confidence_score: int = 0
    is_complete: bool = False
    knowledge: TopicKnowledge = Field(default_factory=TopicKnowledge)
    missing_sections: List[str] = Field(default_factory=list)

class Session(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    topics: List[Topic] = Field(default_factory=list)
    overall_confidence: int = 0
    status: str = "in_progress" # in_progress, completed

class Message(BaseModel):
    role: str # user, assistant
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Optional[Dict] = None
