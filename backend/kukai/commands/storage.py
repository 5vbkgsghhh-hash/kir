"""SQLite storage for user commands."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from kukai.commands.models import UserCommand

if TYPE_CHECKING:
    from kukai.storage.database import Database

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    prompt_instructions TEXT,
    code_template TEXT NOT NULL,
    parameters_schema TEXT,
    verified BOOLEAN DEFAULT FALSE,
    iterations INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tags TEXT
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_user_commands_name ON user_commands(name);
CREATE INDEX IF NOT EXISTS idx_user_commands_tags ON user_commands(tags);
"""


def _row_to_command(row) -> UserCommand:
    """Convert a database row to a UserCommand."""
    return UserCommand(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        prompt_instructions=row["prompt_instructions"] or "",
        code_template=row["code_template"],
        parameters_schema=row["parameters_schema"] or "",
        verified=bool(row["verified"]),
        iterations=row["iterations"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        tags=row["tags"] or "",
    )


class CommandStorage:
    """CRUD operations for user_commands table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def ensure_table(self) -> None:
        """Create user_commands table if not exists."""
        conn = self._db.raw_connection
        await conn.executescript(_CREATE_TABLE_SQL + _CREATE_INDEX_SQL)
        await conn.commit()
        logger.info("user_commands table ensured")

    async def save(self, cmd: UserCommand) -> int:
        """Insert or update command. Returns id."""
        conn = self._db.raw_connection
        now = datetime.now(timezone.utc).isoformat()

        if cmd.id is not None:
            # Update existing
            await conn.execute(
                """UPDATE user_commands
                   SET name=?, description=?, prompt_instructions=?,
                       code_template=?, parameters_schema=?, verified=?,
                       iterations=?, updated_at=?, tags=?
                   WHERE id=?""",
                (
                    cmd.name, cmd.description, cmd.prompt_instructions,
                    cmd.code_template, cmd.parameters_schema, cmd.verified,
                    cmd.iterations, now, cmd.tags, cmd.id,
                ),
            )
            await conn.commit()
            return cmd.id

        # Insert or replace by name
        cursor = await conn.execute(
            """INSERT INTO user_commands
               (name, description, prompt_instructions, code_template,
                parameters_schema, verified, iterations, created_at, updated_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   description=excluded.description,
                   prompt_instructions=excluded.prompt_instructions,
                   code_template=excluded.code_template,
                   parameters_schema=excluded.parameters_schema,
                   verified=excluded.verified,
                   iterations=excluded.iterations,
                   updated_at=excluded.updated_at,
                   tags=excluded.tags""",
            (
                cmd.name, cmd.description, cmd.prompt_instructions,
                cmd.code_template, cmd.parameters_schema, cmd.verified,
                cmd.iterations, now, now, cmd.tags,
            ),
        )
        await conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get(self, name: str) -> UserCommand | None:
        """Get command by name."""
        conn = self._db.raw_connection
        cursor = await conn.execute(
            "SELECT * FROM user_commands WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_command(row)

    async def list_all(self, search: str | None = None) -> list[UserCommand]:
        """List commands, optionally filtered by search in name/description/tags."""
        conn = self._db.raw_connection
        if search:
            pattern = f"%{search}%"
            cursor = await conn.execute(
                """SELECT * FROM user_commands
                   WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
                   ORDER BY updated_at DESC""",
                (pattern, pattern, pattern),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM user_commands ORDER BY updated_at DESC"
            )
        rows = await cursor.fetchall()
        return [_row_to_command(r) for r in rows]

    async def delete(self, name: str) -> bool:
        """Delete command by name. Returns True if deleted."""
        conn = self._db.raw_connection
        cursor = await conn.execute(
            "DELETE FROM user_commands WHERE name = ?", (name,)
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def update_code(self, name: str, code: str, iterations: int) -> bool:
        """Update code template and iteration count after successful execute."""
        conn = self._db.raw_connection
        now = datetime.now(timezone.utc).isoformat()
        cursor = await conn.execute(
            """UPDATE user_commands
               SET code_template=?, iterations=?, updated_at=?
               WHERE name=?""",
            (code, iterations, now, name),
        )
        await conn.commit()
        return cursor.rowcount > 0
