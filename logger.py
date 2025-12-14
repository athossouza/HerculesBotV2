from collections import deque
import datetime
from typing import Dict, Optional

# Global log store
logs_store = deque(maxlen=50)

def add_log(level: str, message: str, metadata: Optional[Dict] = None):
    """
    Adds a log entry to the in-memory store.
    """
    if metadata is None:
        metadata = {}
        
    entry = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": message,
        "metadata": metadata
    }
    logs_store.append(entry)
    # Also print to console for development
    print(f"[{entry['timestamp']}] [{level}] {message}")
