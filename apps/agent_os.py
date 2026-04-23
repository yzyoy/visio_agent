"""
Agno AgentOS entrypoint for the Visio agent — canonical location.

Agno remains the top-level runtime shell. This module:

1. loads the environment (``.env`` via python-dotenv when installed),
2. applies the vsdx monkey-patches **explicitly** via
   ``visio_core.apply_patches()``,
3. wires the DeepSeek model, SqliteDb session store, and the Visio agent,
4. mounts the FastAPI preview router and the static PNG directory used
   by the chat preview.

Launch::

    python -m apps.agent_os
    # or
    python -m uvicorn apps.agent_os:app --reload
"""
from __future__ import annotations

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

from visio_core import apply_patches as _apply_patches

_apply_patches()

from apps.visio_agent import create_visio_agent  # noqa: E402  (after patches)


OpenAIChat.default_role_map = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


def _require_env(var: str) -> str:
    value = os.environ.get(var, "").strip()
    if not value:
        print(
            f"Missing required environment variable: {var}\n"
            f"   Copy .env.example to .env and fill in {var}, or export it "
            f"in your shell before starting the AgentOS.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return value


DEEPSEEK_API_KEY = _require_env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL_ID = os.environ.get("DEEPSEEK_MODEL_ID", "deepseek-chat")
AGNO_SESSIONS_DB = os.environ.get("AGNO_SESSIONS_DB", ".state/agno_sessions.db")
VISIO_TEMPLATE_DIR = os.environ.get("VISIO_TEMPLATE_DIR", "assets/templates")

os.makedirs(".state", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

model = OpenAIChat(
    id=DEEPSEEK_MODEL_ID,
    base_url=DEEPSEEK_BASE_URL,
    api_key=DEEPSEEK_API_KEY,
    name="DeepSeek Chat",
    timeout=120,
    max_retries=3,
)


def _init_sqlite_db(db_file: str) -> SqliteDb:
    """Initialize SqliteDb with a best-effort recovery on corruption."""
    try:
        return SqliteDb(db_file=db_file, session_table="agent_sessions")
    except Exception as e:
        print(f"Database initialization error: {e}")
        if os.path.exists(db_file):
            backup_name = f"{db_file}.error_backup_{int(time.time())}"
            try:
                os.rename(db_file, backup_name)
                print(f"Moved problematic database to: {backup_name}")
            except Exception as rename_err:
                print(f"Could not rename corrupt DB: {rename_err}")
        return SqliteDb(db_file=db_file, session_table="agent_sessions")


db = _init_sqlite_db(AGNO_SESSIONS_DB)

visio_agent = create_visio_agent(
    model=model,
    template_dir=VISIO_TEMPLATE_DIR,
    instruction_profile="full",
    use_dynamic_instructions=True,
    db=db,
)

agent_os = AgentOS(
    id="agent-os",
    description=(
        "AgentOS hosting the Visio agent: template discovery, document "
        "lifecycle, idempotent shape/connector editing, and rendering."
    ),
    agents=[visio_agent],
    db=db,
)

app = agent_os.get_app()


def clear_session(session_id: str):
    """Clear conversation history for a given agno session id."""
    try:
        SqliteDb(db_file=AGNO_SESSIONS_DB).delete_session(session_id)
        print(f"Session {session_id} cleared")
    except Exception as e:
        print(f"Error clearing session {session_id}: {e}")


def list_sessions():
    """List all agno sessions currently stored in the SqliteDb."""
    try:
        sessions = SqliteDb(db_file=AGNO_SESSIONS_DB).get_all_sessions()
        print(f"Total sessions: {len(sessions) if sessions else 0}")
        if sessions:
            for session in sessions:
                msg_count = len(session.messages) if hasattr(session, "messages") else 0
                print(f"- {session.session_id}: {msg_count} messages")
    except Exception as e:
        print(f"Error listing sessions: {e}")


try:
    from visio_core.api.visio_preview import router as visio_preview_router
    app.include_router(visio_preview_router, prefix="/api/visio")
except Exception:
    pass

try:
    from fastapi.staticfiles import StaticFiles
    os.makedirs("outputs/static/visio", exist_ok=True)
    app.mount(
        "/static/visio",
        StaticFiles(directory="outputs/static/visio"),
        name="visio-static",
    )
except Exception:
    pass


if __name__ == "__main__":
    agent_os.serve(app="apps.agent_os:app", reload=True)
