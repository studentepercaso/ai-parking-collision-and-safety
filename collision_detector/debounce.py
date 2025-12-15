"""Gestione debounce e cooldown per eventi collisione."""

from typing import Dict, Tuple


def pair_key(camera_id: str, id1: int, id2: int) -> Tuple[str, int, int]:
    """Crea chiave univoca per coppia veicoli (ordinata)."""
    return (camera_id, min(id1, id2), max(id1, id2))


class DebounceManager:
    """Gestisce debounce per collisioni auto-auto e auto-ostacolo."""
    
    def __init__(self, event_debounce_seconds: float):
        self.EVENT_DEBOUNCE_SECONDS = event_debounce_seconds
        # debounce: (cam, id1, id2) -> last_event_ts per auto-auto
        self.recent_collisions: Dict[Tuple[str, int, int], float] = {}
        # debounce: (cam, vehicle_id, obs_name) -> last_event_ts per auto-ostacolo
        self.recent_obstacle_collisions: Dict[Tuple[str, int, str], float] = {}
    
    def is_debounced(self, camera_id: str, id1: int, id2: int, ts: float) -> bool:
        """Controlla debounce per collisioni auto-auto."""
        key = pair_key(camera_id, id1, id2)
        last_ts = self.recent_collisions.get(key)
        return last_ts is not None and (ts - last_ts) < self.EVENT_DEBOUNCE_SECONDS
    
    def register_event(self, camera_id: str, id1: int, id2: int, ts: float) -> None:
        """Registra evento collisione auto-auto per debounce."""
        self.recent_collisions[pair_key(camera_id, id1, id2)] = ts
    
    def is_obstacle_debounced(self, camera_id: str, vehicle_id: int, obs_name: str, ts: float) -> bool:
        """Controlla debounce per collisioni auto-ostacolo."""
        key = (camera_id, vehicle_id, obs_name)
        last_ts = self.recent_obstacle_collisions.get(key)
        return last_ts is not None and (ts - last_ts) < self.EVENT_DEBOUNCE_SECONDS
    
    def register_obstacle_event(self, camera_id: str, vehicle_id: int, obs_name: str, ts: float) -> None:
        """Registra evento collisione auto-ostacolo per debounce."""
        self.recent_obstacle_collisions[(camera_id, vehicle_id, obs_name)] = ts

