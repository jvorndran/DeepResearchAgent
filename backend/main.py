"""
FastAPI Application Entry Point

This file serves as the main entry point for the Deep Financial Research Agent API.
"""

import json
import uuid
import logging
import os
from contextlib import asynccontextmanager
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

from agents.orchestrator import create_orchestrator, stream_research

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing orchestrator agent (MCP connections, tool registration)...")
    app.state.agent = await create_orchestrator()
    logger.info("Orchestrator ready.")
    yield


app = FastAPI(
    title="Deep Financial Research Agent API",
    description="API for the Deep Financial Research Agent",
    version="0.1.0",
    lifespan=lifespan,
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
async def chat_stream(request: ChatRequest, req: Request):
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
        text_id = "text-1"
        text_started = False
        try:
            # AI SDK v6: send start event
            yield f'data: {json.dumps({"type": "start", "messageId": f"msg-{job_id}"})}\n\n'

            async for chunk in stream_research(query=query, job_id=job_id, messages=messages_dict, agent=req.app.state.agent):
                chunk_type = chunk.get("type")

                if chunk_type == "messages":
                    token, _ = chunk.get("data", (None, None))
                    if token and hasattr(token, "content") and token.content:
                        content = token.content
                        # content may be a plain string or a list of content blocks
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            text = "".join(
                                part.get("text", "") for part in content
                                if isinstance(part, dict) and part.get("type") == "text"
                            )
                        else:
                            text = str(content)
                        if text:
                            if not text_started:
                                yield f'data: {json.dumps({"type": "text-start", "id": text_id})}\n\n'
                                text_started = True
                            yield f'data: {json.dumps({"type": "text-delta", "id": text_id, "delta": text})}\n\n'

                elif chunk_type in ("updates", "custom"):
                    ns = chunk.get("ns", [])
                    data = chunk.get("data", {})
                    serialized_data = serialize_data(data)
                    # Use data-* prefix type so AI SDK v6 routes it to onData callback
                    yield f'data: {json.dumps({"type": "data-pipeline-update", "transient": True, "data": {"type": "update", "ns": ns, "data": serialized_data}})}\n\n'

            if text_started:
                yield f'data: {json.dumps({"type": "text-end", "id": text_id})}\n\n'
            yield f'data: {json.dumps({"type": "finish", "finishReason": "stop"})}\n\n'
            yield 'data: [DONE]\n\n'

        except BaseException as e:
            logger.error(f"Error in stream: {e}")
            yield f'data: {json.dumps({"type": "error", "errorText": str(e)})}\n\n'
            yield 'data: [DONE]\n\n'

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
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["outputs/*", "outputs/**/*"],
    )
