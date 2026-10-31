"""Long-term memory CRUD and the auto-learn switch."""

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.db.models import Memory
from app.db.session import session_factory
from app.schemas.api import MemoryIn, MemoryList, MemoryOut, MemorySettingsIn
from app.services import memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=MemoryList)
async def list_memories() -> MemoryList:
    async with session_factory()() as session:
        rows = (await session.execute(select(Memory).order_by(Memory.created_at.desc()))).scalars().all()
    return MemoryList(auto_learn=await memory.auto_learn_enabled(), memories=[MemoryOut.model_validate(m) for m in rows])


@router.post("", response_model=MemoryOut, status_code=201)
async def add_memory(body: MemoryIn) -> Memory:
    content = " ".join(body.content.split())
    if not content:
        raise HTTPException(422, "Memory is empty")
    async with session_factory()() as session:
        mem = Memory(content=content, source="manual")
        session.add(mem)
        await session.commit()
        await session.refresh(mem)
        return mem


@router.patch("/settings", response_model=MemorySettingsIn)
async def update_settings(body: MemorySettingsIn) -> MemorySettingsIn:
    await memory.set_auto_learn(body.auto_learn)
    return body


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: str, body: MemoryIn) -> Memory:
    content = " ".join(body.content.split())
    if not content:
        raise HTTPException(422, "Memory is empty")
    async with session_factory()() as session:
        mem = await session.get(Memory, memory_id)
        if mem is None:
            raise HTTPException(404, "Memory not found")
        mem.content = content
        mem.source = "manual"  # edited by the user, so it is no longer pruned like an automatic memory
        await session.commit()
        await session.refresh(mem)
        return mem


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: str) -> Response:
    async with session_factory()() as session:
        mem = await session.get(Memory, memory_id)
        if mem is None:
            raise HTTPException(404, "Memory not found")
        await session.delete(mem)
        await session.commit()
    return Response(status_code=204)


@router.delete("", status_code=204)
async def clear_memories() -> Response:
    async with session_factory()() as session:
        await session.execute(delete(Memory))
        await session.commit()
    return Response(status_code=204)
