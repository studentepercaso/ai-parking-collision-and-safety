"""Classe principale CollisionDetector per rilevamento collisioni."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional, Callable
from pathlib import Path
import math

import numpy as np
import cv2

from .config import load_collision_config, load_zones_config
from .utils import point_in_polygon, base64_to_mask
from .debounce import DebounceManager, pair_key
from .tracking import before_after_speed_and_dir
from .mask_analysis import bbox_intersect, iou, mask_intersection
from .collision_logic import is_major_collision, is_minor_collision


class CollisionDetector:
    """
    Rileva possibili collisioni tra veicoli per singola telecamera.

    Uso tipico:
        detector = CollisionDetector(on_event=my_callback)
        events = detector.process_frame(camera_id, objects, timestamp)

    Dove `objects` è una lista di dict:
        {
            "track_id": int,
            "class_id": int,   # usa solo veicoli (car/truck/bus)
            "bbox": (x1, y1, x2, y2),  # in pixel
        }
    """

    MOVING = "MOVING"
    PARKED = "PARKED"

    def __init__(
        self,
        on_event: Optional[Callable[[Dict], None]] = None,
        collision_config_path: Optional[Path] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        # Parametri configurabili (tarati per parcheggi / basse velocità)
        # Se non specificati, vengono caricati da collision_config.json o usati i default
        SPEED_MOVING_THRESHOLD: Optional[float] = None,
        SPEED_PARKED_THRESHOLD: Optional[float] = None,
        MIN_DIST_THRESHOLD: Optional[float] = None,
        IOU_THRESHOLD: Optional[float] = None,
        SPEED_DROP_FACTOR: Optional[float] = None,
        NUDGE_DISTANCE: Optional[float] = None,
        EVENT_DEBOUNCE_SECONDS: Optional[float] = None,
        HISTORY_FRAMES: Optional[int] = None,
        debug_mode: Optional[bool] = None,
    ) -> None:
        self.on_event = on_event
        self.log_callback = log_callback

        # Carica configurazione da file
        file_config = load_collision_config()
        
        # Valori default (se non nel file e non passati come parametri)
        defaults = {
            "SPEED_MOVING_THRESHOLD": 2.0,
            "SPEED_PARKED_THRESHOLD": 0.5,
            "MIN_DIST_THRESHOLD": 100.0,
            "IOU_THRESHOLD": 0.01,
            "SPEED_DROP_FACTOR": 0.7,
            "NUDGE_DISTANCE": 2.0,
            "EVENT_DEBOUNCE_SECONDS": 3.0,
            "HISTORY_FRAMES": 5,
            "debug_mode": True,
            "MAX_COLLISION_DISTANCE": 100.0,
        }
        
        # Usa: parametro passato > file config > default
        param_map = {
            "SPEED_MOVING_THRESHOLD": SPEED_MOVING_THRESHOLD,
            "SPEED_PARKED_THRESHOLD": SPEED_PARKED_THRESHOLD,
            "MIN_DIST_THRESHOLD": MIN_DIST_THRESHOLD,
            "IOU_THRESHOLD": IOU_THRESHOLD,
            "SPEED_DROP_FACTOR": SPEED_DROP_FACTOR,
            "NUDGE_DISTANCE": NUDGE_DISTANCE,
            "EVENT_DEBOUNCE_SECONDS": EVENT_DEBOUNCE_SECONDS,
            "HISTORY_FRAMES": HISTORY_FRAMES,
            "debug_mode": debug_mode,
        }
        for key, param_value in param_map.items():
            setattr(self, key, param_value if param_value is not None else file_config.get(key, defaults[key]))
        self.MAX_COLLISION_DISTANCE = file_config.get("MAX_COLLISION_DISTANCE", defaults["MAX_COLLISION_DISTANCE"])
        
        # Parametri aggiuntivi dal test project per filtro prospettiva e maschere
        self.movement_threshold = file_config.get("movement_threshold", 5.0)
        self.mask_overlap_threshold = file_config.get("mask_overlap_threshold", 0.25)
        self.size_ratio_threshold = file_config.get("size_ratio_threshold", 0.5)
        self.y_position_threshold = file_config.get("y_position_threshold", 0.3)
        self.intersection_ratio_threshold = file_config.get("intersection_ratio_threshold", 0.15)
        self.enable_perspective_filter = file_config.get("enable_perspective_filter", True)

        # Stato per camera_id
        self.last_positions: Dict[str, Dict[int, Tuple[float, float]]] = defaultdict(dict)
        self.last_speeds: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.last_state: Dict[str, Dict[int, str]] = defaultdict(dict)
        self.last_update_ts: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.history: Dict[str, Dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self.HISTORY_FRAMES))
        )  # ogni elemento: (timestamp, cx, cy)

        # Debounce manager
        self.debounce_manager = DebounceManager(self.EVENT_DEBOUNCE_SECONDS)

        # Eventi generati
        self._events: List[Dict] = []
        
        # Cache zone config (caricata lazy)
        self._zones_cache: Optional[Dict] = None
        self._obstacle_masks_cache: Dict[str, Dict[str, np.ndarray]] = {}  # camera_id -> {name: mask}
        
        # Contatori frame per controllo ostacoli (ogni N frame)
        self._frame_counters: Dict[str, int] = defaultdict(int)  # camera_id -> counter
        
        # Tracking avanzato per rilevamento impatti
        self.previous_distances: Dict[Tuple[str, int, int], float] = {}  # (cam, id1, id2) -> distanza
        self.impact_detected_pairs: Dict[Tuple[str, int, int], float] = {}  # (cam, id1, id2) -> timestamp
        self.collision_buffer: Dict[Tuple[str, int, int], List[float]] = {}  # (cam, id1, id2) -> [timestamp1, timestamp2, ...]
        self.min_consecutive_frames = file_config.get("min_consecutive_frames", 2)  # minimo frame consecutivi per validare collisione
        self.impact_cooldown_seconds = file_config.get("impact_cooldown_seconds", 2.0)  # cooldown per impatti rilevati (secondi)
        self.parking_stationary_frames = file_config.get("parking_stationary_frames", 5)  # frame fermi per considerare parcheggio
        self.parking_distance_tolerance = file_config.get("parking_distance_tolerance", 0.03)  # tolleranza distanza per parcheggio (3%)
        self.approach_rate_threshold = file_config.get("approach_rate_threshold", 0.12)  # velocità di avvicinamento per rilevare collisione reale (12%)
        self.distance_increase_threshold = file_config.get("distance_increase_threshold", 1.02)  # soglia per considerare veicoli in allontanamento (2%)
        self.stable_distance_threshold = file_config.get("stable_distance_threshold", 0.995)  # soglia per distanza stabile (0.5%)
        self.min_overlap_ratio = file_config.get("min_overlap_ratio", 0.01)  # soglia minima overlap ratio per maschere (1%)
        self.min_mask_iou = file_config.get("min_mask_iou", 0.005)  # soglia minima IoU maschere (0.5%)
        self.min_bbox_iou = file_config.get("min_bbox_iou", 0.01)  # soglia minima IoU bounding box (1%)
        self.fps_approximation = file_config.get("fps_approximation", 30.0)  # FPS per approssimare timestamp a frame
        self.buffer_gap_threshold = file_config.get("buffer_gap_threshold", 3)  # gap massimo frame per resettare buffer
        self.stationary_frames: Dict[str, Dict[int, int]] = defaultdict(dict)  # camera_id -> {track_id: frame_count}
        self.previous_states: Dict[str, Dict[int, str]] = defaultdict(dict)  # camera_id -> {track_id: stato_precedente}

        # --- Rilevamento persone (loitering / caduta) ---
        self.enable_person_safety = file_config.get("enable_person_safety", True)
        self.enable_person_loitering = file_config.get("enable_person_loitering", True)
        self.enable_person_fall = file_config.get("enable_person_fall", True)
        self.LOITER_SECONDS = file_config.get("LOITER_SECONDS", 20.0)
        self.LOITER_RADIUS = file_config.get("LOITER_RADIUS", 120.0)  # px (baseline 720p, scala con risoluzione nel check)
        self.FALL_ASPECT_RATIO = file_config.get("FALL_ASPECT_RATIO", 0.55)  # w/h sopra questa => possibile caduta
        self.FALL_SPEED_DROP = file_config.get("FALL_SPEED_DROP", 0.45)      # drop di velocità (fattore) rispetto a prima
        self.FALL_MIN_HEIGHT = file_config.get("FALL_MIN_HEIGHT", 40.0)      # bbox height minima per validare caduta

        # Storico persone
        self.person_history = defaultdict(lambda: defaultdict(lambda: deque(maxlen=int(self.fps_approximation * self.LOITER_SECONDS))))
        self.person_last_box = defaultdict(dict)    # camera_id -> {track_id: bbox}
        self.person_last_state = defaultdict(dict)  # camera_id -> {track_id: "STANDING"/"FALLEN"}

        # --- Filtro prospettiva con ground point e strisce inferiori ---
        self.use_ground_point_method = file_config.get("use_ground_point_method", True)  # Usa metodo ground point invece di intera bbox/mask
        self.ground_point_distance_threshold = file_config.get("ground_point_distance_threshold", 50.0)  # Distanza max tra ground point (px)
        self.bottom_strip_height_ratio = file_config.get("bottom_strip_height_ratio", 0.15)  # Percentuale altezza striscia inferiore (15%)
        self.bottom_strip_overlap_ratio = file_config.get("bottom_strip_overlap_ratio", 0.01)  # Soglia overlap strisce inferiori (1%)

    # -------------------- API pubblica --------------------

    def get_events(self) -> List[Dict]:
        return list(self._events)
    
    def _debug_print(self, msg: str) -> None:
        """Stampa messaggio debug se abilitato."""
        if self.debug_mode:
            if self.log_callback:
                self.log_callback(msg)
            else:
                print(msg)
    
    def _log(self, msg: str) -> None:
        """Log sempre (non solo in debug mode)."""
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)
    
    def _load_zones_for_camera(self, camera_id: str) -> Optional[Dict]:
        """Carica configurazione zone per una telecamera (con cache)."""
        if self._zones_cache is None:
            self._zones_cache = load_zones_config()
        return self._zones_cache.get(camera_id)
    
    def _get_obstacle_masks(self, camera_id: str, frame_shape: Tuple[int, int]) -> Dict[str, np.ndarray]:
        """Carica maschere ostacoli per una telecamera (con cache per ogni shape)."""
        cache_key = f"{camera_id}_{frame_shape[0]}_{frame_shape[1]}"  # Include shape nel key
        if cache_key not in self._obstacle_masks_cache:
            zones = self._load_zones_for_camera(camera_id)
            if zones and "obstacles" in zones:
                masks = {}
                for name, obs_data in zones["obstacles"].items():
                    mask = base64_to_mask(obs_data["mask_base64"], tuple(obs_data["shape"]))
                    # Ridimensiona solo se necessario
                    if mask.shape != frame_shape:
                        mask = cv2.resize(mask.astype(np.uint8), (frame_shape[1], frame_shape[0])).astype(bool)
                    masks[name] = mask
                self._obstacle_masks_cache[cache_key] = masks
            else:
                self._obstacle_masks_cache[cache_key] = {}
        return self._obstacle_masks_cache[cache_key]

    def process_frame(
        self,
        camera_id: str,
        objects: List[Dict],
        timestamp: float,
        frame_shape: Optional[Tuple[int, int]] = None,
    ) -> List[Dict]:
        """
        Elabora un frame e ritorna la lista di nuovi eventi collisione (major/minor + ostacoli).
        
        Args:
            camera_id: ID telecamera
            objects: Lista oggetti tracciati
            timestamp: Timestamp frame
            frame_shape: (height, width) del frame (per ridimensionare maschere ostacoli)
        """
        # LOG DIRETTO ALL'INIZIO - SEMPRE STAMPATO
        self._log(f"\n{'='*60}")
        self._log(f"[COLLISION_DETECTOR] process_frame CHIAMATO!")
        self._log(f"[COLLISION_DETECTOR] camera_id={camera_id}")
        self._log(f"[COLLISION_DETECTOR] objects={len(objects)} oggetti")
        self._log(f"[COLLISION_DETECTOR] timestamp={timestamp}")
        self._log(f"[COLLISION_DETECTOR] frame_shape={frame_shape}")
        self._log(f"{'='*60}\n")
        
        events: List[Dict] = []

        # 1) Filtra veicoli (classe a carico del chiamante, ma per default COCO: 2,5,7)
        vehicle_classes = {2, 5, 7}  # Car, Bus, Truck
        self._log(f"[COLLISION_DETECTOR] Filtro veicoli: classi={vehicle_classes}")
        self._log(f"[COLLISION_DETECTOR] Oggetti ricevuti: {[o.get('class_id') for o in objects]}")
        
        vehicles = [o for o in objects if o.get("class_id") in vehicle_classes]
        
        self._log(f"[COLLISION_DETECTOR] Veicoli filtrati: {len(vehicles)} (da {len(objects)} oggetti totali)")
        
        # Persone (class_id COCO = 0)
        person_class = {0}
        persons = [o for o in objects if o.get("class_id") in person_class]

        if self.debug_mode and persons:
            self._debug_print(f"[DEBUG] Persone trovate: {[p.get('track_id') for p in persons]}")
        
        if len(vehicles) > 0:
            for idx, v in enumerate(vehicles):
                self._log(f"[COLLISION_DETECTOR]   Veicolo {idx}: class_id={v.get('class_id')}, track_id={v.get('track_id')}, bbox={v.get('bbox')}")
        
        # Debug: verifica veicoli filtrati
        if self.debug_mode and len(vehicles) >= 2:
            self._debug_print(f"[DEBUG] process_frame: {len(objects)} oggetti totali, {len(vehicles)} veicoli filtrati")
            # Log iniziale per verificare che i log funzionino
            if not hasattr(self, '_first_log_done'):
                self._first_log_done = True
                self._debug_print(f"[DEBUG] Sistema di log attivo - debug_mode={self.debug_mode}")
        
        # 1.5) ROI DISABILITATO SEMPRE (come richiesto)
        # Il filtro ROI è stato disabilitato permanentemente

        # Analizza persone anche se non ci sono abbastanza veicoli
        if self.enable_person_safety and persons:
            self._analyze_persons(camera_id, persons, timestamp, frame_shape, events)

        self._log(f"[COLLISION_DETECTOR] Verifica: len(vehicles)={len(vehicles)}")
        if len(vehicles) < 2:
            self._log(f"[COLLISION_DETECTOR] ⚠️  MENO DI 2 VEICOLI DOPO FILTRI - esco (len={len(vehicles)})")
            return events  # Serve almeno 2 veicoli per collisione
        
        self._log(f"[COLLISION_DETECTOR] ✅ CI SONO {len(vehicles)} VEICOLI - procedo con aggiornamento posizioni")

        # Inizializza contatore log movimento se non esiste (per camera)
        if not hasattr(self, '_movement_log_counter'):
            self._movement_log_counter = {}
        if camera_id not in self._movement_log_counter:
            self._movement_log_counter[camera_id] = 0

        # 2) Aggiorna posizioni, velocità, stato
        cam_last_pos = self.last_positions[camera_id]
        cam_last_speed = self.last_speeds[camera_id]
        cam_last_state = self.last_state[camera_id]
        cam_last_update = self.last_update_ts[camera_id]
        cam_history = self.history[camera_id]

        current_centers: Dict[int, Tuple[float, float]] = {}
        current_boxes: Dict[int, Tuple[float, float, float, float]] = {}
        current_masks: Dict[int, np.ndarray] = {}

        self._log(f"[COLLISION_DETECTOR] Aggiornamento posizioni per {len(vehicles)} veicoli...")
        
        for obj in vehicles:
            try:
                tid = int(obj["track_id"])
                bbox = obj["bbox"]
                self._log(f"[COLLISION_DETECTOR]   Processando veicolo track_id={tid}, bbox={bbox}")
                
                x1, y1, x2, y2 = bbox
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0

                current_centers[tid] = (cx, cy)
                current_boxes[tid] = (x1, y1, x2, y2)
                # mask opzionale (da YOLO-seg), array booleano [H, W]
                if "mask" in obj and obj["mask"] is not None:
                    current_masks[tid] = obj["mask"]
                    self._log(f"[COLLISION_DETECTOR]   Veicolo {tid}: maschera disponibile")
                else:
                    self._log(f"[COLLISION_DETECTOR]   Veicolo {tid}: nessuna maschera")
                
                # Velocità e stato
                prev = cam_last_pos.get(tid)
                inst_speed = math.hypot(cx - prev[0], cy - prev[1]) if prev else 0.0
                new_speed = 0.7 * cam_last_speed.get(tid, 0.0) + 0.3 * inst_speed
                cam_last_speed[tid] = new_speed
                # Determina stato: MOVING se sopra soglia, PARKED se sotto soglia o nuovo veicolo
                old_state = cam_last_state.get(tid, self.PARKED)
                new_state = old_state  # Default: mantieni stato precedente
                
                if new_speed >= self.SPEED_MOVING_THRESHOLD:
                    new_state = self.MOVING
                elif new_speed <= self.SPEED_PARKED_THRESHOLD or tid not in cam_last_state:
                    new_state = self.PARKED
                
                # Aggiorna stato solo se è cambiato (per evitare log eccessivi)
                if new_state != old_state:
                    cam_last_state[tid] = new_state
                    if self.debug_mode:
                        self._debug_print(f"[STATE_CHANGE] Auto {tid}: {old_state} → {new_state} (vel={new_speed:.2f}px/f, soglia_MOVING={self.SPEED_MOVING_THRESHOLD:.2f}, soglia_PARKED={self.SPEED_PARKED_THRESHOLD:.2f})")
                else:
                    cam_last_state[tid] = new_state  # Aggiorna comunque per sicurezza
                
                # Log movimento macchine (ogni 30 frame per non intasare)
                if not hasattr(self, '_movement_log_counter'):
                    self._movement_log_counter = {}
                if camera_id not in self._movement_log_counter:
                    self._movement_log_counter[camera_id] = 0
                self._movement_log_counter[camera_id] += 1
                
                # Log movimento macchine (ogni 10 frame se 2 veicoli, ogni 30 altrimenti)
                log_interval = 10 if len(vehicles) == 2 else 30
                counter = self._movement_log_counter[camera_id]
                if self.debug_mode and counter % log_interval == 0:
                    state_str = cam_last_state.get(tid, self.PARKED)
                    prev_pos_str = f"({prev[0]:.1f},{prev[1]:.1f})" if prev else "N/A"
                    self._debug_print(f"[MOVEMENT] Auto {tid}: pos=({cx:.1f},{cy:.1f}), prev={prev_pos_str}, "
                                    f"vel_inst={inst_speed:.2f}px/f, vel_avg={new_speed:.2f}px/f, "
                                    f"stato={state_str}, bbox=({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f})")
                
                cam_last_pos[tid] = (cx, cy)
                cam_last_update[tid] = timestamp
                cam_history[tid].append((timestamp, cx, cy))
            except Exception as e:
                self._log(f"[COLLISION_DETECTOR] ❌ ERRORE processando veicolo: {e}, obj={obj}")
                import traceback
                self._log(f"[COLLISION_DETECTOR] Traceback: {traceback.format_exc()}")
                continue
        
        self._log(f"[COLLISION_DETECTOR] Posizioni aggiornate: {len(current_centers)} centri, {len(current_boxes)} box")

        # Analisi persone (loitering / caduta)
        if self.enable_person_safety and persons:
            self._analyze_persons(camera_id, persons, timestamp, frame_shape, events)

        # 3) Analizza coppie
        ids = list(current_centers.keys())
        n = len(ids)
        
        # LOG SEMPRE ATTIVO (senza condizioni)
        self._log(f"[DEBUG] ════════════════════════════════════════════════════")
        self._log(f"[DEBUG] process_frame: {len(objects)} oggetti, {len(vehicles)} veicoli, {n} veicoli con centri")
        self._log(f"[DEBUG] IDs veicoli: {ids}")
        self._log(f"[DEBUG] debug_mode={self.debug_mode}")
        
        if n < 2:
            self._log(f"[DEBUG] ⚠️  MENO DI 2 VEICOLI - esco senza analizzare coppie")
            return events
        
        self._log(f"[DEBUG] ✅ CI SONO {n} VEICOLI - analizzo coppie")
        
        for i in range(n):
            for j in range(i + 1, n):
                id1, id2 = ids[i], ids[j]
                self._log(f"[DEBUG] 🔄 Analizzando coppia: Auto {id1} e {id2}")
                c1 = current_centers[id1]
                c2 = current_centers[id2]
                box1 = current_boxes[id1]
                box2 = current_boxes[id2]
                mask1 = current_masks.get(id1)
                mask2 = current_masks.get(id2)

                dist = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                
                # Aggiorna previous_distances per filtro prospettiva
                pair_key_dist = pair_key(camera_id, id1, id2)
                self.previous_distances[pair_key_dist] = dist
                
                # Log dettagliato SEMPRE (senza condizioni)
                is_two_vehicles = len(vehicles) == 2
                # LOG SEMPRE
                self._log(f"[DEBUG] 📊 COPPIA {id1}-{id2}: is_two_vehicles={is_two_vehicles}, debug_mode={self.debug_mode}")
                
                if True:  # SEMPRE logga
                    state1 = cam_last_state.get(id1, self.PARKED)
                    state2 = cam_last_state.get(id2, self.PARKED)
                    speed1 = cam_last_speed.get(id1, 0.0)
                    speed2 = cam_last_speed.get(id2, 0.0)
                    x1_1, y1_1, x2_1, y2_1 = box1
                    x1_2, y1_2, x2_2, y2_2 = box2
                    overlap_x = not (x2_1 < x1_2 or x2_2 < x1_1)
                    overlap_y = not (y2_1 < y1_2 or y2_2 < y1_1)
                    has_mask1 = mask1 is not None
                    has_mask2 = mask2 is not None
                    self._debug_print(f"[PAIR] Auto {id1}({state1}, vel={speed1:.2f}) <-> Auto {id2}({state2}, vel={speed2:.2f}): "
                                    f"distanza={dist:.1f}px, overlap_x={overlap_x}, overlap_y={overlap_y}, "
                                    f"maschere=({has_mask1},{has_mask2}), "
                                    f"box1=({x1_1:.0f},{y1_1:.0f},{x2_1:.0f},{y2_1:.0f}), "
                                    f"box2=({x1_2:.0f},{y1_2:.0f},{x2_2:.0f},{y2_2:.0f})")
                
                # ============================================
                # LOGICA DI RILEVAMENTO COLLISIONI
                # ============================================
                
                # Importa funzioni per ground point e strisce inferiori
                from .mask_analysis import (
                    ground_point_distance, bottom_strip_intersection,
                    get_ground_point, bbox_intersect, iou, mask_intersection
                )
                
                # Calcola IoU (per compatibilità e logging)
                iou_val = iou(box1, box2, mask1, mask2)
                
                # Verifica intersezione usando ground point e strisce inferiori (se abilitato)
                vehicle1_dict = {"bbox": box1, "track_id": id1, "camera_id": camera_id}
                vehicle2_dict = {"bbox": box2, "track_id": id2, "camera_id": camera_id}
                
                has_collision = False
                
                if self.use_ground_point_method:
                    # METODO GROUND POINT: usa solo parte inferiore dei veicoli
                    # 1. Verifica distanza tra ground point
                    gp_dist = ground_point_distance(box1, box2)
                    
                    # Scala soglia con risoluzione se nota
                    gp_threshold = self.ground_point_distance_threshold
                    if frame_shape:
                        scale = max(frame_shape) / 720.0
                        gp_threshold = gp_threshold * scale
                    
                    # 2. Verifica sovrapposizione strisce inferiori
                    strip_overlap = bottom_strip_intersection(
                        mask1, mask2, box1, box2,
                        height_ratio=self.bottom_strip_height_ratio,
                        min_overlap_ratio=self.bottom_strip_overlap_ratio
                    )
                    
                    # Collisione se: ground point vicini OPPURE strisce si sovrappongono
                    # Usa OR invece di AND per essere più permissivo con collisioni reali
                    # Se i ground point sono molto vicini (< 50% soglia), considera collisione anche senza strip_overlap
                    # Se le strisce si sovrappongono, considera collisione anche se ground point sono un po' più lontani
                    very_close_gp = gp_dist <= (gp_threshold * 0.5)  # 50% della soglia = molto vicini
                    close_gp = gp_dist <= gp_threshold  # Entro soglia normale
                    
                    # Collisione se:
                    # - Ground point molto vicini (anche senza strip overlap)
                    # - OPPURE ground point vicini E strisce si sovrappongono
                    has_collision = very_close_gp or (close_gp and strip_overlap)
                    
                    if self.debug_mode:
                        gp1 = get_ground_point(box1)
                        gp2 = get_ground_point(box2)
                        self._debug_print(f"[DEBUG] Ground point method: gp1=({gp1[0]:.1f},{gp1[1]:.1f}), gp2=({gp2[0]:.1f},{gp2[1]:.1f}), "
                                        f"gp_dist={gp_dist:.1f}px (soglia={gp_threshold:.1f}px, molto_vicino={gp_threshold*0.5:.1f}px), "
                                        f"very_close={very_close_gp}, close={close_gp}, strip_overlap={strip_overlap}, "
                                        f"has_collision={has_collision}")
                else:
                    # METODO TRADIZIONALE: usa intera bbox/mask
                    if mask1 is not None and mask2 is not None:
                        # Usa intersezione maschere (più preciso, può rilevare anche quando bbox non si toccano)
                        has_collision = mask_intersection(
                            mask1, mask2, box1, box2,
                            vehicle1_dict, vehicle2_dict,
                            cam_last_state, self.previous_distances,
                            self.enable_perspective_filter,
                            self.min_overlap_ratio, self.min_mask_iou,
                            self.approach_rate_threshold, self.distance_increase_threshold,
                            self.size_ratio_threshold, self.y_position_threshold,
                            self.intersection_ratio_threshold,
                            self.MOVING, self.PARKED
                        )
                        if self.debug_mode:
                            self._debug_print(f"[DEBUG] mask_intersection risultato: {has_collision} per Auto {id1} e {id2}")
                    else:
                        # Fallback: usa intersezione bbox
                        bbox_intersects = bbox_intersect(box1, box2)
                        has_collision = bbox_intersects and iou_val >= self.min_bbox_iou
                    if self.debug_mode:
                        self._debug_print(f"[DEBUG] bbox_intersect={bbox_intersects}, IoU={iou_val:.6f} (soglia={self.min_bbox_iou})")
                
                # Verifica anche distanza (per veicoli molto vicini anche senza intersezione)
                # IMPORTANTE: Se use_ground_point_method è attivo, usa solo has_collision (già calcolato con strisce inferiori)
                # Altrimenti, usa anche near/contact come fallback
                if self.use_ground_point_method:
                    # Con ground point method, usa SOLO has_collision (già calcolato con strisce inferiori)
                    # Non usare near/contact calcolati sull'intera maschera
                    near = False
                    contact = False
                else:
                    # Metodo tradizionale: usa near/contact come fallback
                    near = dist < self.MIN_DIST_THRESHOLD
                    contact = iou_val >= self.IOU_THRESHOLD

                # Soglia distanza massima collisione (scala con risoluzione se nota)
                max_dist = self.MAX_COLLISION_DISTANCE
                if frame_shape:
                    # scala linearmente rispetto al lato maggiore (baseline 720px)
                    scale = max(frame_shape) / 720.0
                    max_dist = max_dist * scale
                
                # Log condizioni
                if self.debug_mode:
                    self._debug_print(f"[DEBUG] Condizioni collisione: Auto {id1} e {id2} - "
                                    f"dist={dist:.1f}px (soglia={self.MIN_DIST_THRESHOLD}), "
                                    f"IoU={iou_val:.6f} (soglia={self.IOU_THRESHOLD}), "
                                    f"near={near}, contact={contact}, has_collision={has_collision}, "
                                    f"use_ground_point={self.use_ground_point_method}")
                
                # Se non c'è collisione e non sono vicini/contatto, oppure sono molto lontani, salta
                too_far = dist > max_dist
                
                # IMPORTANTE: Se use_ground_point_method è attivo, usa SOLO has_collision
                # Altrimenti, usa has_collision OPPURE near/contact come fallback
                if self.use_ground_point_method:
                    # Con ground point method: usa SOLO has_collision (già calcolato con strisce inferiori)
                    if not has_collision or too_far:
                        if self.debug_mode:
                            self._debug_print(f"[DEBUG] NO collisione (ground point): Auto {id1} e {id2} - dist={dist:.1f}px (max={max_dist:.1f}), has_collision={has_collision}, too_far={too_far}")
                        continue
                else:
                    # Metodo tradizionale: usa has_collision OPPURE near/contact
                    if (not has_collision and not (near or contact)) or (too_far and not has_collision):
                        if self.debug_mode:
                            self._debug_print(f"[DEBUG] NO collisione (tradizionale): Auto {id1} e {id2} - dist={dist:.1f}px (max={max_dist:.1f}), IoU={iou_val:.6f}, has_collision={has_collision}, near={near}, contact={contact}")
                        continue
                
                # Se arriviamo qui, c'è una collisione rilevata
                # - Con ground point: has_collision=True (calcolato con strisce inferiori)
                # - Senza ground point: has_collision=True OPPURE near=True OPPURE contact=True
                # Aggiorna buffer temporale SOLO quando c'è collisione
                pair_key_val = pair_key(camera_id, id1, id2)
                if pair_key_val not in self.collision_buffer:
                    self.collision_buffer[pair_key_val] = []
                
                # PRIMA aggiungi il timestamp corrente
                self.collision_buffer[pair_key_val].append(timestamp)
                
                # POI mantieni solo frame recenti (ultimi N secondi) - più permissivo
                # Usa un cutoff molto più largo per permettere gap (10 frame = ~0.33 secondi a 30 FPS)
                cutoff = timestamp - (10.0 / self.fps_approximation)  # ~0.33 secondi a 30 FPS
                self.collision_buffer[pair_key_val] = [t for t in self.collision_buffer[pair_key_val] if t >= cutoff]
                
                # Verifica se ci sono abbastanza frame consecutivi
                buffer_size = len(self.collision_buffer[pair_key_val])
                if buffer_size < self.min_consecutive_frames:
                    if self.debug_mode:
                        self._debug_print(f"[DEBUG] Buffer insufficiente: {buffer_size} < {self.min_consecutive_frames} (buffer: {self.collision_buffer[pair_key_val]})")
                    continue
                
                if self.debug_mode:
                    self._debug_print(f"[DEBUG] Buffer OK: {buffer_size} >= {self.min_consecutive_frames}")
                
                # Stati veicoli
                state1 = cam_last_state.get(id1, self.PARKED)
                state2 = cam_last_state.get(id2, self.PARKED)
                
                # FILTRO CRITICO: Escludi collisioni tra veicoli entrambi fermi (parcheggiati)
                # Due auto parcheggiate vicine non sono una collisione!
                speed1 = cam_last_speed.get(id1, 0.0)
                speed2 = cam_last_speed.get(id2, 0.0)
                
                # Log sempre per verificare stati (non solo in debug)
                self._log(f"[STATES] Auto {id1}: stato={state1}, vel={speed1:.2f}px/f | Auto {id2}: stato={state2}, vel={speed2:.2f}px/f")
                
                if state1 == self.PARKED and state2 == self.PARKED:
                    # ENTRAMBE LE AUTO SONO FERME - NON È UNA COLLISIONE!
                    self._log(f"[FILTER] ⚠️  FILTRATO: Entrambe le auto sono PARKED (ferme) - Auto {id1} (vel={speed1:.2f}px/f) e {id2} (vel={speed2:.2f}px/f) - Non è una collisione!")
                    self._log(f"[FILTER] Soglie: MOVING>={self.SPEED_MOVING_THRESHOLD:.2f}px/f, PARKED<={self.SPEED_PARKED_THRESHOLD:.2f}px/f")
                    if self.debug_mode:
                        self._debug_print(f"[DEBUG] ⚠️  FILTRATO: Entrambe le auto sono PARKED (ferme) - Auto {id1} e {id2} - Non è una collisione!")
                    continue
                
                # Log quando almeno una auto è in movimento (collisione possibile)
                if state1 == self.MOVING or state2 == self.MOVING:
                    self._log(f"[FILTER] ✓ Collisione possibile: Auto {id1} ({state1}, vel={speed1:.2f}) e {id2} ({state2}, vel={speed2:.2f}) - Almeno una in movimento")
                
                # Calcola velocità e direzione per classificazione
                hist1 = cam_history.get(id1, deque())
                hist2 = cam_history.get(id2, deque())
                v1_before, v1_after, dir1_change = before_after_speed_and_dir(hist1)
                v2_before, v2_after, dir2_change = before_after_speed_and_dir(hist2)
                
                # Classifica collisione
                major = is_major_collision(
                    v1_before, v1_after, v2_before, v2_after,
                    dir1_change, dir2_change,
                    self.SPEED_MOVING_THRESHOLD, self.SPEED_DROP_FACTOR
                )
                minor = is_minor_collision(
                    state1, state2, hist1, hist2,
                    cam_last_speed.get(id1, 0.0), cam_last_speed.get(id2, 0.0),
                    self.MOVING, self.PARKED, self.NUDGE_DISTANCE, self.SPEED_PARKED_THRESHOLD
                )
                base_collision = not (major or minor)  # Base se non è major né minor
                
                # Verifica debounce
                if self.debounce_manager.is_debounced(camera_id, id1, id2, timestamp):
                    if self.debug_mode:
                        self._debug_print(f"[DEBUG] Debounced: Auto {id1} e {id2}")
                    continue
                
                # Crea evento
                event_type = "collision_auto_auto_major" if major else \
                            "collision_auto_auto_minor" if minor else \
                            "collision_auto_auto_base"
                
                event = {
                    "type": event_type,
                    "camera_id": camera_id,
                    "timestamp": timestamp,
                    "vehicle_ids": [id1, id2],
                    "details": {
                        "distance": dist,
                        "iou": iou_val,
                        "state1": state1,
                        "state2": state2,
                        "bbox1": box1,
                        "bbox2": box2,
                        "v1_before": v1_before,
                        "v1_after": v1_after,
                        "v2_before": v2_before,
                        "v2_after": v2_after,
                        "dir1_change": dir1_change,
                        "dir2_change": dir2_change,
                    },
                }
                
                self.debounce_manager.register_event(camera_id, id1, id2, timestamp)
                self._events.append(event)
                events.append(event)
                
                if self.on_event:
                    self.on_event(event)
                
                if self.debug_mode:
                    self._debug_print(f"[DEBUG] ✅ Collisione rilevata: {event_type} - Auto {id1} e {id2}")

        # 4) Controlla collisioni con ostacoli (ogni 3 frame per performance)
        if frame_shape:
            self._frame_counters[camera_id] += 1
            if self._frame_counters[camera_id] % 3 == 0:
                obstacle_masks = self._get_obstacle_masks(camera_id, frame_shape)
                if obstacle_masks:
                    resized_masks = {}
                    for tid, obj_mask in current_masks.items():
                        if obj_mask is not None and len(obj_mask.shape) == 2 and obj_mask.shape[0] > 0 and obj_mask.shape[1] > 0:
                            resized_masks[tid] = (obj_mask if obj_mask.shape == frame_shape else
                                                cv2.resize(obj_mask.astype(np.uint8), (frame_shape[1], frame_shape[0])).astype(bool))
                    
                    for tid in current_centers.keys():
                        if tid not in resized_masks and tid in current_boxes:
                            x1, y1, x2, y2 = [int(c) for c in current_boxes[tid]]
                            x1, y1 = max(0, min(x1, frame_shape[1] - 1)), max(0, min(y1, frame_shape[0] - 1))
                            x2, y2 = max(x1 + 1, min(x2, frame_shape[1])), max(y1 + 1, min(y2, frame_shape[0]))
                            mask = np.zeros(frame_shape, dtype=bool)
                            mask[y1:y2, x1:x2] = True
                            resized_masks[tid] = mask
                    
                    for tid, obj_mask in resized_masks.items():
                        for obs_name, obs_mask in obstacle_masks.items():
                            intersection = np.logical_and(obj_mask, obs_mask).sum()
                            if intersection > 10 and not self.debounce_manager.is_obstacle_debounced(camera_id, tid, obs_name, timestamp):
                                event = {
                                    "type": "collision_auto_ostacolo",
                                    "camera_id": camera_id,
                                    "timestamp": timestamp,
                                    "vehicle_id": tid,
                                    "obstacle_name": obs_name,
                                    "details": {"intersection_pixels": int(intersection)},
                                }
                                self.debounce_manager.register_obstacle_event(camera_id, tid, obs_name, timestamp)
                                self._events.append(event)
                                events.append(event)
                                if self.on_event:
                                    self.on_event(event)

        # LOG FINALE - SEMPRE STAMPATO
        self._log(f"[COLLISION_DETECTOR] 🔚 process_frame TERMINATO: restituisco {len(events)} eventi")
        self._log(f"[COLLISION_DETECTOR] 🔚 Tipo di events: {type(events)}")
        self._log(f"[COLLISION_DETECTOR] 🔚 ID di events: {id(events)}")
        if events:
            self._log(f"[COLLISION_DETECTOR] 🔚 Eventi da restituire:")
            for idx, ev in enumerate(events):
                self._log(f"[COLLISION_DETECTOR]   {idx+1}. type={ev.get('type')}, vehicle_ids={ev.get('vehicle_ids')}")
        else:
            self._log(f"[COLLISION_DETECTOR] ⚠️  NESSUN EVENTO da restituire (lista vuota)")
        
        # VERIFICA FINALE
        result = events
        self._log(f"[COLLISION_DETECTOR] 🔚 RETURN: restituisco lista con {len(result)} eventi")
        return result

    # -------------------- Analisi persone --------------------
    def _analyze_persons(self, camera_id, persons, timestamp, frame_shape, events):
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
                if self.enable_person_loitering:
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
                            if self.debug_mode:
                                self._debug_print(
                                    f"[DEBUG] 🚶‍♂️ Loitering: persona {tid}, durata={duration:.1f}s, span={span:.1f}px (raggio={loiter_radius:.1f})"
                                )

                # --- FALL DETECTION ---
                if self.enable_person_fall:
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
                        if self.debug_mode:
                            self._debug_print(f"[DEBUG] 🤕 Caduta: persona {tid}, aspect={aspect:.2f}, bbox={bbox}")
                    else:
                        # reset se torna in piedi
                        if aspect < self.FALL_ASPECT_RATIO * 0.8:
                            cam_last_state[tid] = "STANDING"

                cam_last_box[tid] = bbox
            except Exception as e:
                self._log(f"[COLLISION_DETECTOR] ❌ ERRORE persone: {e}, obj={p}")
                import traceback
                self._log(f"[COLLISION_DETECTOR] Traceback: {traceback.format_exc()}")

