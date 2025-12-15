"""EventLogger - Modulo core per logging eventi strutturati."""

import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any


class EventLogger:
    """Logger per eventi in formato JSON strutturato."""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.lock = threading.Lock()
    
    def log(self, event_type: str, details: str = "", track_id: int = None, **kwargs):
        """Aggiunge evento al log."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "details": details,
            "track_id": track_id,
            **kwargs,
        }
        with self.lock:
            self.events.append(event)
    
    def save(self):
        """Salva log su file JSON."""
        with self.lock:
            if self.events:
                # Leggi eventi esistenti se file esiste
                existing = []
                if self.log_file.exists():
                    try:
                        with open(self.log_file, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except (json.JSONDecodeError, IOError):
                        existing = []
                
                # Aggiungi nuovi eventi
                all_events = existing + self.events
                
                # Salva
                with open(self.log_file, "w", encoding="utf-8") as f:
                    json.dump(all_events, f, indent=2, ensure_ascii=False)
                
                self.events = []  # Pulisci buffer dopo salvataggio

