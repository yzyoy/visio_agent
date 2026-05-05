import json
import sqlite3

db = r"c:\Data\data\agent\.state\agno_sessions.db"
conn = sqlite3.connect(db)
row = conn.execute(
    """
    SELECT session_id, session_data, runs, updated_at
    FROM agent_sessions
    ORDER BY COALESCE(updated_at, created_at) DESC
    LIMIT 1
    """
).fetchone()
sid, sd_raw, runs_raw, updated_at = row

runs = json.loads(json.loads(runs_raw))
print("session_id", sid, "runs count", len(runs))
for i, run in enumerate(runs):
    msgs = run.get("messages") or []
    ev = run.get("events") or []
    content = run.get("content")
    cp = (content[:80] + "...") if isinstance(content, str) and len(content) > 80 else content
    print(f"run {i}: messages={len(msgs)} events={len(ev)} content_preview={cp!r}")

sd = json.loads(json.loads(sd_raw))
print("\nsession_data keys", list(sd.keys()))
metrics = sd.get("session_metrics") or {}
print("session_metrics keys", list(metrics.keys())[:15])
state = sd.get("session_state")
print("session_state type", type(state).__name__, state if state else "(empty)")

conn.close()
