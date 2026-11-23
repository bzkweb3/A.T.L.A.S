"""Conversation history and long-term memory endpoints."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/conversations", tags=["memoria"])
memory_router = APIRouter(prefix="/api/memory", tags=["memoria de longo prazo"])


class FactInput(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)


@router.get("")
async def list_conversations(request: Request) -> dict:
    return {"conversations": request.app.state.memory.list_conversations()}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict:
    conversation = request.app.state.memory.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation


@memory_router.get("")
async def list_long_term_memory(request: Request) -> dict:
    facts = request.app.state.long_term_memory.list_facts()
    return {"facts": facts, "count": len(facts)}


@memory_router.delete("/facts/{category}/{key}")
async def delete_memory_fact(category: str, key: str, request: Request) -> dict:
    deleted = request.app.state.long_term_memory.forget(category, key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Informação não encontrada na memória.")
    return {"deleted": True, "category": category, "key": key}


@memory_router.post("/facts")
async def save_memory_fact(payload: FactInput, request: Request) -> dict:
    return {"saved": request.app.state.long_term_memory.remember(
        payload.category, payload.key, payload.value, source="user"
    )}
