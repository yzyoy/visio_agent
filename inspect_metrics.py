import json
import sqlite3

db = r"c:\Data\data\agent\.state\agno_sessions.db"
conn = sqlite3.connect(db)
row = conn.execute(
    """
    SELECT session_data, runs
    FROM agent_sessions
    ORDER BY COALESCE(updated_at, created_at) DESC
    LIMIT 1
    """
).fetchone()
sd_raw, runs_raw = row
runs = json.loads(json.loads(runs_raw))
sd = json.loads(json.loads(sd_raw))

for i, run in enumerate(runs):
    m = run.get("metrics") or {}
    print(f"run {i} metrics keys:", list(m.keys()) if isinstance(m, dict) else m)
    print(f"  sample:", {k: m.get(k) for k in list(m.keys())[:8]} if isinstance(m, dict) else "")

print("\nsession_metrics:", json.dumps(sd.get("session_metrics"), indent=2)[:1200])

conn.close()
