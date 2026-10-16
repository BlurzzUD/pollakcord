import sqlite3

from alembic import command

from .test_migrations import alembic_config


def test_bot_revision_preserves_existing_humans_and_media_in_both_directions(tmp_path):
    database = tmp_path / "existing.db"
    config = alembic_config(f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "0005")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users (id, username, username_lower, display_name, status, platform_role, created_at) VALUES (100, 'human', 'human', 'Human', 'active', 'user', '2026-01-01T10:00:00')")
        connection.execute("INSERT INTO profiles (user_id, bio, avatar_key, banner_key, updated_at) VALUES (100, 'preserved', 'avatar.webp', 'banner.webp', '2026-01-01T10:00:00')")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        media_columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
    command.upgrade(config, "0006")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT username, is_bot FROM users WHERE id = 100").fetchone() == ("human", 0)
        assert connection.execute("SELECT bio, avatar_key, banner_key FROM profiles WHERE user_id = 100").fetchone() == ("preserved", "avatar.webp", "banner.webp")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    command.downgrade(config, "0005")
    with sqlite3.connect(database) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables
        assert {row[1] for row in connection.execute("PRAGMA table_info(messages)")} == media_columns
        assert connection.execute("SELECT username FROM users WHERE id = 100").fetchone() == ("human",)
        assert connection.execute("SELECT bio FROM profiles WHERE user_id = 100").fetchone() == ("preserved",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
