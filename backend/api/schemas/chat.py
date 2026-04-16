from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: Optional[str] = None
    parts: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    messages: List[Message]
    job_id: Optional[str] = None
    stream_telemetry: Optional[bool] = Field(
        default=None,
        description="False = omit raw model tokens; client uses user_message SSE from emit_chat_message.",
    )
