from datetime import timezone
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text

from app.api.dependencies.container import get_container
from app.core.common.time import utc_now
from app.core.context_manager import current_user_id_ctx
from app.service.container import ServiceContainer


async def get_current_user_id(
    request: Request,
    container: ServiceContainer = Depends(get_container),
) -> str:
    """Extract session token from header or cookie, verify it, and set the RLS context."""
    # 1. Extract session token
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    if not token:
        token = request.cookies.get("better-auth.session_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: Missing session token.",
        )

    # 2. Query session table
    # Since session table has no RLS, we can read it to identify the user
    async with container.context_manager.session() as db_session:
        stmt = text("""
            SELECT "userId", "expiresAt" FROM "session"
            WHERE token = :token LIMIT 1
        """)
        result = await db_session.execute(stmt, {"token": token})
        row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: Invalid session token.",
        )

    user_id, expires_at = row

    # Ensure expires_at is timezone-aware
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # Check expiration
    if expires_at < utc_now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: Session expired.",
        )

    # 3. Propagate the user ID to the RLS ContextVar
    current_user_id_ctx.set(user_id)
    return user_id
