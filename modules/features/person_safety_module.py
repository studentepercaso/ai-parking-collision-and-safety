"""Person Safety Module - Rilevamento loitering e cadute (INDIPENDENTE da CollisionDetector)."""

from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional, Callable
from pathlib import Path
import json


class PersonSafetyDetector:
    """
    Rilevamento sicurezza persone - INDIPENDENTE da CollisionDetector.
    
    Funzionalità:
    - Person Loitering: rileva persone che stanno troppo tempo in un'area
    - Person Fall Detection: rileva cadute basandosi su aspect ratio e drop velocità
    """
    
    def __init__(
        self,
        enable_loitering: bool = True,
        enable_fall: bool = True,
        on_event: Optional[Callable[[Dict], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        config_path: Optional[Path] = None,
        loiter_seconds: float = 20.0,
        loiter_radius: float = 120.0,
        fall_aspect_ratio: float = 0.55,
        fall_speed_drop: float = 0.45,
        fall_min_height: float = 40.0,
        fps_approximation: float = 30.0,
        debug_mode: bool = False,
    ):
        """
        Args:
            enable_loitering: Abilita rilevamento loitering
            enable_fall: Abilita rilevamento cadute
            on_event: Callback chiamato quando viene rilevato un evento
            log_callback: Callback per logging
            config_path: Path a file di configurazione JSON
            loiter_seconds: Secondi minimi per considerare loitering
            loiter_radius: Raggio massimo (px) per considerare loitering
            fall_aspect_ratio: Soglia aspect ratio (w/h) per caduta
            fall_speed_drop: Fattore drop velocità per caduta
            fall_min_height: Altezza minima bbox per validare caduta
            fps_approximation: FPS approssimato per calcolo storico
            debug_mode: Abilita logging dettagliato
        """
        self.enable_loitering = enable_loitering
        self.enable_fall = enable_fall
        self.on_event = on_event
        self.log_callback = log_callback
        self.debug_mode = debug_mode
        
        # Carica configurazione se disponibile
        if config_path and config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    loiter_seconds = config.get("LOITER_SECONDS", loiter_seconds)
                    loiter_radius = config.get("LOITER_RADIUS", loiter_radius)
                    fall_aspect_ratio = config.get("FALL_ASPECT_RATIO", fall_aspect_ratio)
                    fall_speed_drop = config.get("FALL_SPEED_DROP", fall_speed_drop)
                    fall_min_height = config.get("FALL_MIN_HEIGHT", fall_min_height)
                    fps_approximation = config.get("fps_approximation", fps_approximation)
            except Exception as e:
                self._log(f"Errore caricamento config: {e}")
        
        # Parametri
        self.LOITER_SECONDS = loiter_seconds
        self.LOITER_RADIUS = loiter_radius
        self.FALL_ASPECT_RATIO = fall_aspect_ratio
        self.FALL_SPEED_DROP = fall_speed_drop
        self.FALL_MIN_HEIGHT = fall_min_height
        self.fps_approximation = fps_approximation
        
        # Storico persone (camera_id -> track_id -> deque)
        self.person_history = defaultdict(
            lambda: defaultdict(
                lambda: deque(maxlen=int(fps_approximation * loiter_seconds))
            )
        )
        self.person_last_box = defaultdict(dict)    # camera_id -> {track_id: bbox}
        self.person_last_state = defaultdict(dict)  # camera_id -> {track_id: "STANDING"/"FALLEN"}
        
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
    
    def process_persons(
        self,
        camera_id: str,
        persons: List[Dict],
        timestamp: float,
        frame_shape: Optional[Tuple[int, int]] = None,
    ) -> List[Dict]:
        """
        Processa persone e ritorna eventi (loitering/fall).
        
        Args:
            camera_id: ID telecamera
            persons: Lista persone tracciate [{track_id, bbox, ...}]
            timestamp: Timestamp frame
            frame_shape: (height, width) del frame per scalare parametri
            
        Returns:
            Lista eventi rilevati
        """
        events = []
        cam_hist = self.person_history[camera_id]
        cam_last_box = self.person_last_box[camera_id]
        cam_last_state = self.person_last_state[camera_id]
        
        for p in persons:
            try:
                tid = int(p.get("track_id"))
                bbox = p.get("bbox")
                if not bbox:
                    continue
                
                x1, y1, x2, y2 = bbox
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                w = max(1.0, x2 - x1)
                h = max(1.0, y2 - y1)
                
                # Aggiorna storico centri
                cam_hist[tid].append((timestamp, cx, cy))
                
                # Scala parametri su risoluzione se frame_shape noto
                loiter_radius = self.LOITER_RADIUS
                if frame_shape:
                    scale = max(frame_shape) / 720.0
                    loiter_radius = self.LOITER_RADIUS * scale
                
                # --- LOITERING ---
                if self.enable_loitering:
                    hist = list(cam_hist[tid])
                    if hist:
                        xs = [c[1] for c in hist]
                        ys = [c[2] for c in hist]
                        span = max((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2, 0) ** 0.5
                        duration = hist[-1][0] - hist[0][0]
                        if duration >= self.LOITER_SECONDS and span <= loiter_radius:
                            ev = {
                                "type": "person_loitering",
                                "camera_id": camera_id,
                                "timestamp": timestamp,
                                "person_id": tid,
                                "details": {"duration_s": duration, "span_px": span, "bbox": bbox},
                            }
                            self._events.append(ev)
                            events.append(ev)
                            if self.on_event:
                                self.on_event(ev)
                            self._debug_print(
                                f"[PersonSafety] 🚶‍♂️ Loitering: persona {tid}, durata={duration:.1f}s, span={span:.1f}px (raggio={loiter_radius:.1f})"
                            )
                
                # --- FALL DETECTION ---
                if self.enable_fall:
                    prev_state = cam_last_state.get(tid, "STANDING")
                    aspect = w / h
                    fall_shape = aspect >= self.FALL_ASPECT_RATIO and h >= self.FALL_MIN_HEIGHT
                    
                    hist = list(cam_hist[tid])
                    fall_speed_drop = False
                    if len(hist) >= 2:
                        (t_prev, cx_prev, cy_prev) = hist[-2]
                        dt = max(1e-3, timestamp - t_prev)
                        speed_prev = abs(cy - cy_prev) / dt
                        if len(hist) >= 3:
                            (t_prev2, cx_prev2, cy_prev2) = hist[-3]
                            dt2 = max(1e-3, t_prev - t_prev2)
                            speed_before = abs(cy_prev - cy_prev2) / dt2
                            if speed_before > 0 and speed_prev < speed_before * self.FALL_SPEED_DROP:
                                fall_speed_drop = True
                    
                    if fall_shape and fall_speed_drop and prev_state != "FALLEN":
                        ev = {
                            "type": "person_fall",
                            "camera_id": camera_id,
                            "timestamp": timestamp,
                            "person_id": tid,
                            "details": {"aspect": aspect, "bbox": bbox},
                        }
                        self._events.append(ev)
                        events.append(ev)
                        cam_last_state[tid] = "FALLEN"
                        if self.on_event:
                            self.on_event(ev)
                        self._debug_print(
                            f"[PersonSafety] 🤕 Caduta: persona {tid}, aspect={aspect:.2f}, bbox={bbox}"
                        )
                    else:
                        # Reset se torna in piedi
                        if aspect < self.FALL_ASPECT_RATIO * 0.8:
                            cam_last_state[tid] = "STANDING"
                
                cam_last_box[tid] = bbox
            except Exception as e:
                self._log(f"[PersonSafety] ❌ ERRORE persona: {e}, obj={p}")
                import traceback
                self._log(f"[PersonSafety] Traceback: {traceback.format_exc()}")
        
        return events
    
    def get_events(self) -> List[Dict]:
        """Restituisce lista eventi generati."""
        return list(self._events)
    
    def clear_events(self):
        """Pulisce lista eventi."""
        self._events.clear()

