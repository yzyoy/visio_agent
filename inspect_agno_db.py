import json
import sqlite3

db = r"c:\Data\data\agent\.state\agno_sessions.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute(
    """
    SELECT session_id, created_at, updated_at,
           session_data, agent_data, runs, summary, metadata
    FROM agent_sessions
    ORDER BY COALESCE(updated_at, created_at) DESC
    LIMIT 1
    """
)
row = cur.fetchone()
print("Latest session_id:", row["session_id"])

for key in ("session_data", "agent_data", "runs", "summary", "metadata"):
    raw = row[key]
    print(f"\n=== {key} === python_type={type(raw).__name__}")
    if raw is None:
        continue
    if isinstance(raw, str):
        print("first 300 chars:", repr(raw[:300]))
    else:
        print("value:", raw)

def parse_json_maybe(val, depth=0):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", errors="replace")
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return val
        if s[0] in "{[":
            try:
                inner = json.loads(val)
                if depth < 3 and isinstance(inner, str) and inner.strip()[:1] in "{[":
                    return parse_json_maybe(inner, depth + 1)
                return inner
            except json.JSONDecodeError:
                return val
    return val

for key in ("session_data", "agent_data", "runs"):
    raw = row[key]
    data = parse_json_maybe(raw)
    print(f"\n>>> parsed {key}: type={type(data).__name__}")
    if isinstance(data, dict):
        print("keys:", list(data.keys()))
        for k, v in list(data.items())[:20]:
            if isinstance(v, list):
                print(f"  {k}: list len={len(v)}")
            elif isinstance(v, dict):
                print(f"  {k}: dict keys={list(v.keys())}")
            else:
                print(f"  {k}: {str(v)[:100]}")
    elif isinstance(data, list):
        print("len:", len(data))
        for i, item in enumerate(data[:5]):
            print(f"  [{i}] {type(item).__name__}: {str(item)[:150]}")

conn.close()
