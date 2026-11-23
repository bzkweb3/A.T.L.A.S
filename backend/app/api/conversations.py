"""Conversation history endpoints backed by local SQLite."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/conversations", tags=["memoria"])


@router.get("")
async def list_conversations(request: Request) -> dict:
    """List recent conversations without returning their full contents."""
    return {"conversations": request.app.state.memory.list_conversations()}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict:
    """Load one conversation and its messages."""
    conversation = request.app.state.memory.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation
