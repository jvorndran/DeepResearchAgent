"""
FastAPI Application Entry Point

This file serves as the main entry point for the Deep Financial Research Agent API.
"""

import json
import uuid
import logging
import os
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

# Load environment variables from .env file
# Try to load from the backend directory first
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.orchestrator import stream_research

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Deep Financial Research Agent API",
    description="API for the Deep Financial Research Agent",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],  # Next.js frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    parts: Optional[List[Dict[str, Any]]] = None

class ChatRequest(BaseModel):
    messages: List[Message]
    job_id: Optional[str] = None

@app.get("/health")
async def health_check():
    return {"status": "ok"}

def serialize_data(data: Any) -> Any:
    """Helper to serialize complex objects from LangGraph."""
    if isinstance(data, dict):
        return {k: serialize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_data(v) for v in data]
    elif hasattr(data, "dict"):
        return data.dict()
    elif hasattr(data, "model_dump"):
        return data.model_dump()
    else:
        return str(data)

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    job_id = request.job_id or f"job_{uuid.uuid4().hex[:8]}"
    
    # Convert Pydantic messages to dicts for LangGraph
    messages_dict = []
    for msg in request.messages:
        content = msg.content
        if not content and msg.parts:
            # Extract text from parts if content is not directly provided
            text_parts = [p.get("text", "") for p in msg.parts if p.get("type") == "text"]
            content = "".join(text_parts)
            
        messages_dict.append({"role": msg.role, "content": content or ""})
    
    # Get the latest query (last user message)
    query = ""
    for msg in reversed(messages_dict):
        if msg["role"] == "user":
            query = msg["content"]
            break
            
    async def event_generator():
        try:
            async for chunk in stream_research(query=query, job_id=job_id, messages=messages_dict):
                chunk_type = chunk.get("type")
                
                if chunk_type == "messages":
                    token, _ = chunk.get("data", (None, None))
                    if token and hasattr(token, "content") and token.content:
                        # Vercel AI SDK Text format: 0:"text"\n
                        text = token.content
                        yield f'0:{json.dumps(text)}\n'
                        
                elif chunk_type == "updates":
                    ns = chunk.get("ns", [])
                    data = chunk.get("data", {})
                    
                    # Serialize data to ensure it's JSON serializable
                    serialized_data = serialize_data(data)
                    
                    update_data = {
                        "type": "update",
                        "ns": ns,
                        "data": serialized_data
                    }
                    
                    yield f'2:[{json.dumps(update_data)}]\n'
                    
                elif chunk_type == "custom":
                    ns = chunk.get("ns", [])
                    data = chunk.get("data", {})
                    
                    custom_data = {
                        "type": "custom",
                        "ns": ns,
                        "data": serialize_data(data)
                    }
                    
                    yield f'2:[{json.dumps(custom_data)}]\n'
                    
        except Exception as e:
            logger.error(f"Error in stream: {e}")
            # Vercel AI SDK Error format: 3:"error message"\n
            yield f'3:{json.dumps(str(e))}\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
