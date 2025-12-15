"""
Person-Vehicle Interaction Module - Rilevamento persone che girano intorno a veicoli.
"""

from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional, Callable, Set
from pathlib import Path
import json
import math


class PersonVehicleInteractionDetector:
    """
    Rileva quando una persona si muove intorno a più veicoli o mostra comportamenti sospetti.
    
    Funzionalità:
    - Traccia quando una persona si avvicina a più veicoli
    - Rileva pattern circolari intorno a veicoli
    - Monitora tempo passato vicino a veicoli
    """
    
    def __init__(
        self,
        on_event: Optional[Callable[[Dict], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        config_path: Optional[Path] = None,
        proximity_threshold: float = 150.0,  # Distanza in pixel per considerare "vicino"
        min_vehicles_visited: int = 2,  # Numero minimo di veicoli per generare evento
        min_time_near_vehicle: float = 3.0,  # Secondi minimi vicino a un veicolo
        circular_pattern_threshold: float = 200.0,  # Raggio per pattern circolare
        fps_approximation: float = 30.0,
        debug_mode: bool = False,
    ):
        """
        Args:
            on_event: Callback chiamato quando viene rilevato un evento
            log_callback: Callback per logging
            config_path: Path a file di configurazione JSON
            proximity_threshold: Distanza massima (px) per considerare persona "vicino" a veicolo
            min_vehicles_visited: Numero minimo di veicoli diversi visitati per evento
            min_time_near_vehicle: Tempo minimo (s) vicino a un veicolo per contarlo
            circular_pattern_threshold: Raggio per rilevare pattern circolare
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
                    proximity_threshold = config.get("PERSON_VEHICLE_PROXIMITY_THRESHOLD", proximity_threshold)
                    min_vehicles_visited = config.get("MIN_VEHICLES_VISITED", min_vehicles_visited)
                    min_time_near_vehicle = config.get("MIN_TIME_NEAR_VEHICLE", min_time_near_vehicle)
                    circular_pattern_threshold = config.get("CIRCULAR_PATTERN_THRESHOLD", circular_pattern_threshold)
            except Exception as e:
                self._log(f"Errore caricamento config: {e}")
        
        # Parametri
        self.PROXIMITY_THRESHOLD = proximity_threshold
        self.MIN_VEHICLES_VISITED = min_vehicles_visited
        self.MIN_TIME_NEAR_VEHICLE = min_time_near_vehicle
        self.CIRCULAR_PATTERN_THRESHOLD = circular_pattern_threshold
        self.fps_approximation = fps_approximation
        
        # Storico per ogni persona: {camera_id: {person_id: deque di (timestamp, person_pos, nearby_vehicles)}}
        self.person_history = defaultdict(
            lambda: defaultdict(
                lambda: deque(maxlen=int(fps_approximation * 30))  # Ultimi 30 secondi
            )
        )
        
        # Traccia veicoli visitati da ogni persona: {camera_id: {person_id: Set[vehicle_id]}}
        self.vehicles_visited_by_person = defaultdict(lambda: defaultdict(set))
        
        # Tempo passato vicino a veicoli: {camera_id: {person_id: {vehicle_id: (first_time, last_time)}}}
        self.time_near_vehicles = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [None, None])))
        
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
    
    def _calculate_distance(self, bbox1: Tuple[float, float, float, float], 
                           bbox2: Tuple[float, float, float, float]) -> float:
        """Calcola distanza tra centri di due bounding box."""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        cx1 = (x1_1 + x2_1) / 2.0
        cy1 = (y1_1 + y2_1) / 2.0
        cx2 = (x1_2 + x2_2) / 2.0
        cy2 = (y1_2 + y2_2) / 2.0
        
        return math.sqrt((cx1 - cx2)**2 + (cy1 - cy2)**2)
    
    def _find_nearby_vehicles(self, person_bbox: Tuple[float, float, float, float], 
                              vehicles: List[Dict]) -> List[Tuple[int, float]]:
        """Trova veicoli vicini a una persona."""
        nearby = []
        for v in vehicles:
            vehicle_bbox = v.get("bbox")
            if not vehicle_bbox:
                continue
            
            distance = self._calculate_distance(person_bbox, vehicle_bbox)
            if distance <= self.PROXIMITY_THRESHOLD:
                vehicle_id = v.get("track_id")
                if vehicle_id is not None:
                    nearby.append((int(vehicle_id), distance))
        
        return nearby
    
    def _detect_circular_pattern(self, history: List[Tuple[float, float, float]]) -> bool:
        """Rileva se il pattern di movimento è circolare intorno a un punto."""
        if len(history) < 10:  # Serve almeno 10 punti per pattern circolare
            return False
        
        # Estrai posizioni
        positions = [(x, y) for _, x, y in history]
        
        # Calcola centro geometrico
        cx = sum(x for x, y in positions) / len(positions)
        cy = sum(y for x, y in positions) / len(positions)
        
        # Calcola distanze dal centro
        distances = [math.sqrt((x - cx)**2 + (y - cy)**2) for x, y in positions]
        avg_distance = sum(distances) / len(distances)
        
        # Se la distanza media è relativamente costante, potrebbe essere un pattern circolare
        if avg_distance > 50:  # Minimo raggio
            std_dev = math.sqrt(sum((d - avg_distance)**2 for d in distances) / len(distances))
            # Coefficiente di variazione basso = distanza costante = possibile cerchio
            cv = std_dev / avg_distance if avg_distance > 0 else 1.0
            if cv < 0.5 and avg_distance <= self.CIRCULAR_PATTERN_THRESHOLD:
                return True
        
        return False
    
    def process_frame(
        self,
        camera_id: str,
        persons: List[Dict],
        vehicles: List[Dict],
        timestamp: float,
        frame_shape: Optional[Tuple[int, int]] = None,
    ) -> List[Dict]:
        """
        Processa frame e rileva interazioni persona-veicolo.
        
        Args:
            camera_id: ID telecamera
            persons: Lista persone tracciate [{track_id, bbox, ...}]
            vehicles: Lista veicoli tracciati [{track_id, bbox, ...}]
            timestamp: Timestamp frame
            frame_shape: (height, width) del frame per scalare parametri
            
        Returns:
            Lista eventi rilevati
        """
        events = []
        cam_history = self.person_history[camera_id]
        cam_vehicles_visited = self.vehicles_visited_by_person[camera_id]
        cam_time_near = self.time_near_vehicles[camera_id]
        
        # Scala threshold in base alla risoluzione
        proximity_threshold = self.PROXIMITY_THRESHOLD
        if frame_shape:
            scale = max(frame_shape) / 720.0
            proximity_threshold = self.PROXIMITY_THRESHOLD * scale
        
        for person in persons:
            try:
                person_id = int(person.get("track_id", -1))
                person_bbox = person.get("bbox")
                if not person_bbox or person_id < 0:
                    continue
                
                x1, y1, x2, y2 = person_bbox
                person_cx = (x1 + x2) / 2.0
                person_cy = (y1 + y2) / 2.0
                
                # Trova veicoli vicini
                nearby_vehicles = self._find_nearby_vehicles(person_bbox, vehicles)
                
                # Aggiorna storico
                cam_history[person_id].append((timestamp, person_cx, person_cy))
                
                # Aggiorna veicoli visitati e tempo passato vicino
                for vehicle_id, distance in nearby_vehicles:
                    cam_vehicles_visited[person_id].add(vehicle_id)
                    
                    # Aggiorna tempo vicino a questo veicolo
                    if cam_time_near[person_id][vehicle_id][0] is None:
                        cam_time_near[person_id][vehicle_id][0] = timestamp  # First time
                    cam_time_near[person_id][vehicle_id][1] = timestamp  # Last time
                
                # Verifica se la persona ha visitato abbastanza veicoli
                vehicles_visited = cam_vehicles_visited[person_id]
                if len(vehicles_visited) >= self.MIN_VEHICLES_VISITED:
                    # Verifica tempo passato vicino ai veicoli
                    total_time_near = 0.0
                    vehicles_with_sufficient_time = 0
                    
                    for vehicle_id in vehicles_visited:
                        first_time, last_time = cam_time_near[person_id][vehicle_id]
                        if first_time is not None and last_time is not None:
                            time_near = last_time - first_time
                            if time_near >= self.MIN_TIME_NEAR_VEHICLE:
                                vehicles_with_sufficient_time += 1
                                total_time_near += time_near
                    
                    # Se ha visitato abbastanza veicoli e ha passato tempo sufficiente
                    if vehicles_with_sufficient_time >= self.MIN_VEHICLES_VISITED:
                        # Verifica pattern circolare
                        hist = list(cam_history[person_id])
                        is_circular = self._detect_circular_pattern(hist)
                        
                        ev = {
                            "type": "person_around_vehicles",
                            "camera_id": camera_id,
                            "timestamp": timestamp,
                            "person_id": person_id,
                            "details": {
                                "vehicles_visited": list(vehicles_visited),
                                "num_vehicles": len(vehicles_visited),
                                "total_time_near_vehicles": total_time_near,
                                "circular_pattern": is_circular,
                                "current_nearby": [vid for vid, _ in nearby_vehicles],
                            },
                        }
                        
                        # Genera evento solo una volta per questa combinazione persona-veicoli
                        event_key = f"{camera_id}_{person_id}_{len(vehicles_visited)}"
                        if not hasattr(self, '_generated_events'):
                            self._generated_events = set()
                        
                        # Genera evento solo se non già generato per questa combinazione
                        if event_key not in self._generated_events:
                            self._generated_events.add(event_key)
                            self._events.append(ev)
                            events.append(ev)
                            if self.on_event:
                                self.on_event(ev)
                            
                            pattern_desc = "pattern circolare" if is_circular else "movimento sospetto"
                            self._debug_print(
                                f"[PersonVehicle] 🚶‍♂️🚗 Persona {person_id} ha visitato {len(vehicles_visited)} veicoli "
                                f"({vehicles_visited}) con {pattern_desc}, tempo totale: {total_time_near:.1f}s"
                            )
                        else:
                            # Reset evento se la persona visita più veicoli
                            # Rimuovi eventi precedenti per questa persona e genera nuovo evento
                            old_key = event_key
                            # Cerca eventi esistenti per questa persona con meno veicoli
                            for prev_key in list(self._generated_events):
                                if prev_key.startswith(f"{camera_id}_{person_id}_"):
                                    prev_num = int(prev_key.split('_')[-1])
                                    if prev_num < len(vehicles_visited):
                                        # Genera nuovo evento se ha visitato più veicoli
                                        self._generated_events.remove(prev_key)
                                        break
                            
                            # Se abbiamo rimosso un vecchio evento, genera quello nuovo
                            if old_key not in self._generated_events:
                                self._generated_events.add(event_key)
                                self._events.append(ev)
                                events.append(ev)
                                if self.on_event:
                                    self.on_event(ev)
                                
                                pattern_desc = "pattern circolare" if is_circular else "movimento sospetto"
                                self._debug_print(
                                    f"[PersonVehicle] 🚶‍♂️🚗 Persona {person_id} ha visitato {len(vehicles_visited)} veicoli "
                                    f"({vehicles_visited}) con {pattern_desc}, tempo totale: {total_time_near:.1f}s"
                                )
                
            except Exception as e:
                self._log(f"[PersonVehicle] ❌ ERRORE elaborazione persona: {e}")
                import traceback
                if self.debug_mode:
                    self._log(f"[PersonVehicle] Traceback: {traceback.format_exc()}")
        
        return events
    
    def get_events(self) -> List[Dict]:
        """Restituisce lista eventi generati."""
        return list(self._events)
    
    def clear_events(self):
        """Pulisce lista eventi."""
        self._events.clear()
        if hasattr(self, '_generated_events'):
            self._generated_events.clear()

