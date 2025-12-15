"""
Person Wall Writing Detection Module - Rilevamento persone che scrivono su muri.
"""

from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional, Callable
from pathlib import Path
import json
import math


class PersonWallWritingDetector:
    """
    Rileva quando una persona sta scrivendo su un muro.
    
    Strategia:
    - Rileva persone vicino ai bordi del frame (presunti muri)
    - Analizza movimento del bounding box per pattern di scrittura
    - Rileva movimenti ripetitivi verticali/orizzontali tipici della scrittura
    """
    
    def __init__(
        self,
        on_event: Optional[Callable[[Dict], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        config_path: Optional[Path] = None,
        wall_proximity_threshold: float = 50.0,  # Distanza in pixel dai bordi per considerare "vicino al muro"
        min_writing_duration: float = 3.0,  # Secondi minimi di attività sospetta
        movement_variance_threshold: float = 15.0,  # Varianza minima movimento per considerare scrittura
        min_movement_frequency: float = 0.5,  # Movimenti al secondo minimi per scrittura
        fps_approximation: float = 30.0,
        debug_mode: bool = False,
    ):
        """
        Args:
            on_event: Callback chiamato quando viene rilevato un evento
            log_callback: Callback per logging
            config_path: Path a file di configurazione JSON
            wall_proximity_threshold: Distanza dai bordi (px) per considerare persona vicino a muro
            min_writing_duration: Tempo minimo (s) di attività per considerare scrittura
            movement_variance_threshold: Varianza movimento minima per pattern di scrittura
            min_movement_frequency: Frequenza movimenti minima (movimenti/s)
            fps_approximation: FPS approssimato per calcolo storico
            debug_mode: Abilita logging dettagliato
        """
        self.on_event = on_event
        self.log_callback = log_callback
        self.debug_mode = debug_mode
        
        # Carica configurazione se disponibile
        if config_path and config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    wall_proximity_threshold = config.get("WALL_PROXIMITY_THRESHOLD", wall_proximity_threshold)
                    min_writing_duration = config.get("MIN_WRITING_DURATION", min_writing_duration)
                    movement_variance_threshold = config.get("MOVEMENT_VARIANCE_THRESHOLD", movement_variance_threshold)
                    min_movement_frequency = config.get("MIN_MOVEMENT_FREQUENCY", min_movement_frequency)
            except Exception as e:
                self._log(f"Errore caricamento config: {e}")
        
        # Parametri
        self.WALL_PROXIMITY_THRESHOLD = wall_proximity_threshold
        self.MIN_WRITING_DURATION = min_writing_duration
        self.MOVEMENT_VARIANCE_THRESHOLD = movement_variance_threshold
        self.MIN_MOVEMENT_FREQUENCY = min_movement_frequency
        self.fps_approximation = fps_approximation
        
        # Storico per ogni persona: {camera_id: {person_id: deque di (timestamp, x1, y1, x2, y2, center_x, center_y, movement)}}
        self.person_history = defaultdict(
            lambda: defaultdict(
                lambda: deque(maxlen=int(fps_approximation * min_writing_duration * 2))  # Doppio tempo minimo
            )
        )
        
        # Traccia se persona è vicina a muro: {camera_id: {person_id: (is_near_wall, start_time)}}
        self.person_near_wall = defaultdict(lambda: defaultdict(lambda: [False, None]))
        
        # Eventi generati
        self._events: List[Dict] = []
    
    def _log(self, msg: str):
        """Log messaggio."""
        if self.log_callback:
            self.log_callback(msg)
        elif self.debug_mode:
            print(msg)
    
    def _debug_print(self, msg: str):
        """Stampa messaggio debug se abilitato."""
        if self.debug_mode:
            self._log(msg)
    
    def _is_near_wall(self, bbox: Tuple[float, float, float, float], 
                      frame_shape: Tuple[int, int],
                      proximity_threshold: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """
        Verifica se una persona è vicina a un bordo (presunto muro).
        
        Args:
            bbox: Bounding box persona
            frame_shape: (height, width) del frame
            proximity_threshold: Soglia distanza (opzionale, usa self.WALL_PROXIMITY_THRESHOLD se None)
        
        Returns:
            (is_near, wall_side) dove wall_side è 'left', 'right', 'top', 'bottom' o None
        """
        if proximity_threshold is None:
            proximity_threshold = self.WALL_PROXIMITY_THRESHOLD
        
        x1, y1, x2, y2 = bbox
        frame_h, frame_w = frame_shape
        
        # Verifica vicinanza a ogni bordo
        distance_left = x1
        distance_right = frame_w - x2
        distance_top = y1
        distance_bottom = frame_h - y2
        
        min_distance = min(distance_left, distance_right, distance_top, distance_bottom)
        
        if min_distance <= proximity_threshold:
            if min_distance == distance_left:
                return True, 'left'
            elif min_distance == distance_right:
                return True, 'right'
            elif min_distance == distance_top:
                return True, 'top'
            else:
                return True, 'bottom'
        
        return False, None
    
    def _calculate_movement_pattern(self, history: List[Tuple[float, float, float, float, float, float]]) -> Dict:
        """
        Analizza pattern di movimento per rilevare scrittura.
        
        Args:
            history: Lista di (timestamp, x1, y1, x2, y2, center_x, center_y, prev_movement)
        
        Returns:
            Dict con informazioni sul pattern: variance, frequency, is_writing_pattern
        """
        if len(history) < 5:  # Serve almeno 5 punti per analisi
            return {"variance": 0, "frequency": 0, "is_writing_pattern": False}
        
        # Estrai posizioni del centro
        centers_x = [h[5] for h in history]
        centers_y = [h[6] for h in history]
        
        # Calcola varianze
        if len(centers_x) > 1:
            mean_x = sum(centers_x) / len(centers_x)
            mean_y = sum(centers_y) / len(centers_y)
            
            var_x = sum((x - mean_x)**2 for x in centers_x) / len(centers_x)
            var_y = sum((y - mean_y)**2 for y in centers_y) / len(centers_y)
            
            # Varianza combinata (movimento generale)
            total_variance = math.sqrt(var_x + var_y)
        else:
            total_variance = 0
        
        # Calcola frequenza di movimento (cambi di direzione)
        movements = [h[7] for h in history if h[7] is not None]  # prev_movement
        direction_changes = 0
        for i in range(1, len(movements)):
            if movements[i] != movements[i-1] and movements[i] is not None and movements[i-1] is not None:
                direction_changes += 1
        
        # Frequenza = cambi di direzione / durata
        duration = history[-1][0] - history[0][0]
        frequency = direction_changes / duration if duration > 0 else 0
        
        # Pattern di scrittura: varianza moderata + alta frequenza cambi direzione
        is_writing_pattern = (
            total_variance >= self.MOVEMENT_VARIANCE_THRESHOLD and
            frequency >= self.MIN_MOVEMENT_FREQUENCY
        )
        
        return {
            "variance": total_variance,
            "frequency": frequency,
            "is_writing_pattern": is_writing_pattern,
            "direction_changes": direction_changes
        }
    
    def _calculate_movement_direction(self, prev_center: Tuple[float, float], 
                                     curr_center: Tuple[float, float]) -> Optional[str]:
        """Calcola direzione movimento rispetto al centro precedente."""
        if prev_center is None:
            return None
        
        dx = curr_center[0] - prev_center[0]
        dy = curr_center[1] - prev_center[1]
        
        # Soglia per considerare movimento significativo
        threshold = 2.0
        
        if abs(dx) < threshold and abs(dy) < threshold:
            return None  # Nessun movimento significativo
        elif abs(dx) > abs(dy):
            return 'horizontal'
        else:
            return 'vertical'
    
    def process_persons(
        self,
        camera_id: str,
        persons: List[Dict],
        timestamp: float,
        frame_shape: Optional[Tuple[int, int]] = None,
    ) -> List[Dict]:
        """
        Processa persone e rileva attività di scrittura su muro.
        
        Args:
            camera_id: ID telecamera
            persons: Lista persone tracciate [{track_id, bbox, ...}]
            timestamp: Timestamp frame
            frame_shape: (height, width) del frame
            
        Returns:
            Lista eventi rilevati
        """
        if frame_shape is None:
            return []
        
        events = []
        cam_history = self.person_history[camera_id]
        cam_near_wall = self.person_near_wall[camera_id]
        
        # Scala threshold in base alla risoluzione
        wall_proximity = self.WALL_PROXIMITY_THRESHOLD
        scale = max(frame_shape) / 720.0
        wall_proximity = self.WALL_PROXIMITY_THRESHOLD * scale
        
        for person in persons:
            try:
                person_id = int(person.get("track_id", -1))
                person_bbox = person.get("bbox")
                if not person_bbox or person_id < 0:
                    continue
                
                x1, y1, x2, y2 = person_bbox
                center_x = (x1 + x2) / 2.0
                center_y = (y1 + y2) / 2.0
                
                # Verifica se persona è vicina a un muro (usa threshold scalato)
                is_near, wall_side = self._is_near_wall(person_bbox, frame_shape, wall_proximity)
                
                # Calcola movimento rispetto al frame precedente
                prev_movement = None
                if cam_history[person_id]:
                    prev_entry = cam_history[person_id][-1]
                    prev_center = (prev_entry[5], prev_entry[6])  # center_x, center_y
                    curr_center = (center_x, center_y)
                    prev_movement = self._calculate_movement_direction(prev_center, curr_center)
                
                # Aggiorna storico
                cam_history[person_id].append((
                    timestamp,
                    x1, y1, x2, y2,  # bbox
                    center_x, center_y,  # center
                    prev_movement  # movement direction
                ))
                
                # Aggiorna stato vicinanza al muro
                was_near_wall, wall_start_time = cam_near_wall[person_id]
                
                if is_near:
                    if not was_near_wall:
                        # Appena arrivato vicino al muro
                        cam_near_wall[person_id] = [True, timestamp]
                        wall_start_time = timestamp
                    # Persona ancora vicino al muro
                    duration_near_wall = timestamp - wall_start_time if wall_start_time else 0
                    
                    # Analizza pattern di movimento solo se è vicino al muro da abbastanza tempo
                    if duration_near_wall >= self.MIN_WRITING_DURATION:
                        hist = list(cam_history[person_id])
                        # Filtra solo punti quando era vicino al muro
                        near_wall_history = [h for h in hist if h[0] >= wall_start_time]
                        
                        if len(near_wall_history) >= 5:
                            movement_pattern = self._calculate_movement_pattern(near_wall_history)
                            
                            if movement_pattern["is_writing_pattern"]:
                                # Genera evento scrittura su muro
                                ev = {
                                    "type": "person_wall_writing",
                                    "camera_id": camera_id,
                                    "timestamp": timestamp,
                                    "person_id": person_id,
                                    "details": {
                                        "wall_side": wall_side,
                                        "duration_near_wall": duration_near_wall,
                                        "movement_variance": movement_pattern["variance"],
                                        "movement_frequency": movement_pattern["frequency"],
                                        "direction_changes": movement_pattern["direction_changes"],
                                        "bbox": person_bbox,
                                    },
                                }
                                
                                # Genera evento solo una volta per questa persona
                                event_key = f"{camera_id}_{person_id}_wall_writing"
                                if not hasattr(self, '_generated_writing_events'):
                                    self._generated_writing_events = set()
                                
                                if event_key not in self._generated_writing_events:
                                    self._generated_writing_events.add(event_key)
                                    self._events.append(ev)
                                    events.append(ev)
                                    if self.on_event:
                                        self.on_event(ev)
                                    
                                    self._debug_print(
                                        f"[WallWriting] ✍️ Persona {person_id} sta scrivendo su muro {wall_side}, "
                                        f"durata: {duration_near_wall:.1f}s, varianza: {movement_pattern['variance']:.1f}, "
                                        f"frequenza: {movement_pattern['frequency']:.2f} mov/s"
                                    )
                else:
                    # Persona non più vicino al muro, reset stato
                    if was_near_wall:
                        cam_near_wall[person_id] = [False, None]
                        # Reset evento generato per permettere nuovo rilevamento
                        if hasattr(self, '_generated_writing_events'):
                            event_key = f"{camera_id}_{person_id}_wall_writing"
                            if event_key in self._generated_writing_events:
                                self._generated_writing_events.remove(event_key)
                
            except Exception as e:
                self._log(f"[WallWriting] ❌ ERRORE elaborazione persona: {e}")
                import traceback
                if self.debug_mode:
                    self._log(f"[WallWriting] Traceback: {traceback.format_exc()}")
        
        return events
    
    def get_events(self) -> List[Dict]:
        """Restituisce lista eventi generati."""
        return list(self._events)
    
    def clear_events(self):
        """Pulisce lista eventi."""
        self._events.clear()
        if hasattr(self, '_generated_writing_events'):
            self._generated_writing_events.clear()

