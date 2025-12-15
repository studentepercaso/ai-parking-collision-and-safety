"""StatisticsCollector - Modulo core per statistiche real-time."""

import threading
import time
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional


class StatisticsCollector:
    """Raccoglie statistiche durante lo streaming/elaborazione in modo thread-safe."""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()
    
    def reset(self):
        """Reset tutte le statistiche."""
        with self.lock:
            self.frame_count = 0
            self.start_time = time.time()
            
            # FPS
            self.current_fps = 0.0
            self.avg_fps = 0.0
            self.fps_history = deque(maxlen=30)  # Ultimi 30 secondi
            
            # Oggetti tracciati
            self.current_objects = {"cars": 0, "persons": 0}
            self.total_objects_seen = {"cars": set(), "persons": set()}  # Set di ID visti
            self.active_track_ids = {"cars": [], "persons": []}
            
            # Eventi
            self.events = deque(maxlen=100)  # Ultimi 100 eventi
            
            # Log messages
            self.log_messages = deque(maxlen=500)  # Ultimi 500 messaggi di log
            
            # Performance
            self.processing_times = deque(maxlen=100)
            self.last_frame_time = None
            
            # Stato
            self.status = "STOPPED"  # STOPPED, RUNNING, PAUSED, ERROR
            self.error_message = None
    
    def update_frame(self, num_cars: int = 0, num_persons: int = 0, 
                     car_ids: List[int] = None, person_ids: List[int] = None,
                     processing_time: float = None):
        """Aggiorna statistiche per un frame processato."""
        with self.lock:
            self.frame_count += 1
            self.current_objects = {"cars": num_cars, "persons": num_persons}
            
            if car_ids:
                self.active_track_ids["cars"] = car_ids
                self.total_objects_seen["cars"].update(car_ids)
            
            if person_ids:
                self.active_track_ids["persons"] = person_ids
                self.total_objects_seen["persons"].update(person_ids)
            
            # Calcola FPS
            now = time.time()
            if self.last_frame_time:
                frame_time = now - self.last_frame_time
                if frame_time > 0:
                    fps = 1.0 / frame_time
                    self.fps_history.append(fps)
                    self.current_fps = fps
                    if len(self.fps_history) > 0:
                        self.avg_fps = sum(self.fps_history) / len(self.fps_history)
            
            self.last_frame_time = now
            
            if processing_time:
                self.processing_times.append(processing_time)
    
    def add_event(self, event_type: str, details: str = "", track_id: int = None):
        """Aggiunge un evento alla lista."""
        with self.lock:
            event = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": event_type,
                "details": details,
                "track_id": track_id,
            }
            self.events.appendleft(event)  # Più recenti prima
    
    def get_stats(self) -> Dict:
        """Restituisce tutte le statistiche come dizionario."""
        with self.lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            return {
                "frame_count": self.frame_count,
                "current_fps": self.current_fps,
                "avg_fps": self.avg_fps,
                "current_objects": self.current_objects.copy(),
                "total_cars_seen": len(self.total_objects_seen["cars"]),
                "total_persons_seen": len(self.total_objects_seen["persons"]),
                "active_track_ids": {
                    "cars": self.active_track_ids["cars"][:10],  # Max 10
                    "persons": self.active_track_ids["persons"][:10],
                },
                "events": list(self.events)[:20],  # Ultimi 20 eventi
                "log_messages": list(self.log_messages)[:200],  # Ultimi 200 log
                "status": self.status,
                "error_message": self.error_message,
                "uptime_seconds": int(elapsed),
                "avg_processing_time": (
                    sum(self.processing_times) / len(self.processing_times)
                    if len(self.processing_times) > 0 else 0
                ),
            }
    
    def add_log(self, message: str):
        """Aggiunge messaggio di log."""
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}"
            self.log_messages.appendleft(log_entry)  # Più recenti prima
            # Stampa anche su console per debug
            print(log_entry)
    
    def get_logs(self, max_lines: int = 100) -> List[str]:
        """Restituisce ultimi N messaggi di log."""
        with self.lock:
            return list(self.log_messages)[:max_lines]
    
    def set_status(self, status: str, error_message: str = None):
        """Imposta stato sistema."""
        with self.lock:
            self.status = status
            self.error_message = error_message

