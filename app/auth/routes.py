"""
Authentication HTTP routes (local email/password for M2.2).

These endpoints depend only on the provider-agnostic ``AuthService`` and the
shared ``get_current_user`` dependency, so federated providers can be added
without touching this module (they add their own callback routes and reuse the
same session/user machinery).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.base import AuthError, UserAlreadyExistsError
from app.auth.service import AuthService
from app.auth.tokens import TokenError, TokenPair
from app.db.models import User
from app.dependencies import get_auth_service, get_current_user
from app.models import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


@router.post("/signup", response_model=TokenResponse, status_code=201, summary="Register")
async def signup(
    payload: SignupRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Register a new local user and return tokens."""
    try:
        _user, pair = await auth_service.signup(payload.email, payload.password, payload.name)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    return _tokens(pair)


@router.post("/login", response_model=TokenResponse, summary="Log in")
async def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Authenticate with email/password and return tokens."""
    try:
        _user, pair = await auth_service.login(
            {"email": payload.email, "password": payload.password}
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    return _tokens(pair)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh tokens")
async def refresh(
    payload: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Exchange a refresh token for a new token pair."""
    try:
        pair = await auth_service.refresh(payload.refresh_token)
    except (TokenError, AuthError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from exc
    return _tokens(pair)


@router.get("/me", response_model=UserResponse, summary="Current user")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        is_verified=current_user.is_verified,
    )
