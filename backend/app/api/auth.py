"""Local owner authentication and session/device management."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.app.core.auth import AuthService, CSRF_COOKIE, DEVICE_COOKIE, SESSION_COOKIE

router = APIRouter(prefix="/api/auth", tags=["autenticação"])


class LoginInput(BaseModel):
    password: str
    device_label: str = Field(default="Dispositivo local", min_length=1, max_length=80)


async def require_authenticated(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    session = request.app.state.auth_repository.get_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Sessão expirada ou revogada.")
    request.state.auth_session = session
    return session


@router.get("/csrf")
async def csrf_token(request: Request, response: Response) -> dict:
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/", max_age=86400)
    return {"csrf_token": token}


@router.get("/status")
async def auth_status(request: Request) -> dict:
    return {"owner_configured": request.app.state.auth_repository.owner_exists()}


@router.post("/login")
async def login(payload: LoginInput, request: Request, response: Response) -> dict:
    repository = request.app.state.auth_repository
    if not repository.owner_exists():
        raise HTTPException(status_code=503, detail="A senha mestra ainda não foi configurada pelo proprietário no computador local.")
    service: AuthService = request.app.state.auth_service
    if not service.authenticate(payload.password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas ou acesso temporariamente bloqueado.")
    token, session = service.issue_session(
        request.cookies.get(DEVICE_COOKIE), payload.device_label,
        request.headers.get("user-agent", "")[:160],
    )
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/", max_age=30 * 86400)
    response.set_cookie(DEVICE_COOKIE, session["device_id"], httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/", max_age=365 * 86400)
    return {"authenticated": True, "session_id": session["id"], "device_id": session["device_id"]}


@router.post("/logout")
async def logout(request: Request, response: Response, _session: dict = Depends(require_authenticated)) -> dict:
    request.app.state.auth_repository.revoke_token(request.cookies.get(SESSION_COOKIE, ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"logged_out": True}


@router.get("/sessions")
async def list_sessions(request: Request, _session: dict = Depends(require_authenticated)) -> dict:
    return {"sessions": request.app.state.auth_repository.list_sessions()}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request, response: Response, session: dict = Depends(require_authenticated)) -> dict:
    deleted = request.app.state.auth_repository.revoke_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    if session["id"] == session_id:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return {"revoked": True}


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, request: Request, response: Response, session: dict = Depends(require_authenticated)) -> dict:
    if not request.app.state.auth_repository.revoke_device(device_id):
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
    if session["device_id"] == device_id:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return {"revoked": True, "device_id": device_id}
