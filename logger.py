import sqlite3
import json
import datetime
from typing import Dict, Optional, List

# Use the same DB as workflow for simplicity
DB_FILE = "sessions.db"

def _init_log_db():
    """Ensure the logs table exists."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                level TEXT,
                message TEXT,
                metadata TEXT
            )
        """)
        conn.commit()

# Initialize on module load
_init_log_db()

def add_log(level: str, message: str, metadata: Optional[Dict] = None):
    """
    Adds a log entry to the SQLite database.
    """
    if metadata is None:
        metadata = {}
        
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO logs (timestamp, level, message, metadata)
                VALUES (?, ?, ?, ?)
            """, (timestamp, level, message, json.dumps(metadata)))
            conn.commit()
    except Exception as e:
        print(f"FAILED TO LOG TO DB: {e}")

    # Also print to console for development
    print(f"[{timestamp}] [{level}] {message}")

def get_logs(limit: int = 100) -> List[Dict]:
    """Retrieve recent logs from DB."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            # Return dict-like rows
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
            logs = []
            for row in rows:
                meta = {}
                try:
                    meta = json.loads(row["metadata"])
                except:
                    pass
                
                logs.append({
                    "timestamp": row["timestamp"],
                    "level": row["level"],
                    "message": row["message"],
                    "metadata": meta
                })
            return logs
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return []

def get_log_stats() -> Dict[str, int]:
    """Count errors and warnings from logs."""
    stats = {"ERROR": 0, "WARN": 0}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT level, COUNT(*) FROM logs WHERE level IN ('ERROR', 'WARN') GROUP BY level")
            rows = cursor.fetchall()
            for level, count in rows:
                stats[level] = count
    except Exception as e:
        print(f"Error log stats: {e}")
    return stats

def clear_logs():
    """Clear all logs."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM logs")
        conn.commit()

# Backward compatibility alias (mocking deque behavior for read only if needed, but we should update main.py)
# logs_store = ... (Removed, main.py MUST be updated)
