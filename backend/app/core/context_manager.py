from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.database.postgres import PostgresProvider

# Context variable to hold the current user ID for RLS enforcement
current_user_id_ctx: ContextVar[str | None] = ContextVar("current_user_id_ctx", default=None)


class ContextManager:
    """Owns the database connection lifecycle for the application.

    Created once at startup and stored on app.state.
    Pass into services and DAOs via dependency injection.
    Call initialize() before use and close() on shutdown.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._postgres: PostgresProvider | None = None

    async def initialize(self) -> None:
        """Create the database engine and session factory. Call once at startup."""
        conn_str = self._settings.APP_DB_CONNECTION_STRING or self._settings.POSTGRES_CONNECTION_STRING
        self._postgres = PostgresProvider(
            connection_string=conn_str,
            connection_settings={
                "pool_size": 5,
                "max_overflow": 10,
                "pool_timeout": 30,
                "pool_recycle": 1800,
                "pool_pre_ping": True,
                "echo": self._settings.ENVIRONMENT == "development",
            },
        )

    async def close(self) -> None:
        """Dispose the database engine. Call on shutdown."""
        if self._postgres:
            await self._postgres.close()
            self._postgres = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a database session. Commits on clean exit, rolls back on exception."""
        if self._postgres is None:
            raise RuntimeError("ContextManager not initialized. Call initialize() first.")
        async with await self._postgres.get_session() as session:
            try:
                user_id = current_user_id_ctx.get()
                if user_id is not None:
                    await session.execute(
                        text("SELECT set_config('app.current_user_id', :user_id, true)"),
                        {"user_id": user_id}
                    )
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> bool:
        """Check live database connectivity. Used by GET /health."""
        if self._postgres is None:
            return False
        return await self._postgres.health_check()
