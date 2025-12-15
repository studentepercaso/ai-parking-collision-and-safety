"""Analisi maschere e prospettiva per collision detector."""

from typing import Dict, Optional, Tuple
import math

import numpy as np
import cv2


def bbox_intersect(b1, b2) -> bool:
    """
    Verifica se due bounding box si intersecano.
    Args:
        b1, b2: (x1, y1, x2, y2) formato bounding box
    Returns:
        True se c'è intersezione, False altrimenti
    """
    x1_1, y1_1, x2_1, y2_1 = b1
    x1_2, y1_2, x2_2, y2_2 = b2
    
    # Verifica sovrapposizione
    if x2_1 < x1_2 or x2_2 < x1_1:
        return False
    if y2_1 < y1_2 or y2_2 < y1_1:
        return False
    
    return True


def iou(b1, b2, m1: Optional[np.ndarray] = None, m2: Optional[np.ndarray] = None) -> float:
    """
    Calcola IoU usando, se disponibili, le maschere di segmentazione;
    altrimenti ricade sulle bounding box.
    MIGLIORATO: Soglie più basse per maschere per rilevare contatti leggeri.
    """
    # Se abbiamo entrambe le maschere, usiamo IoU su mask (molto più preciso)
    if m1 is not None and m2 is not None:
        try:
            mask1 = m1.astype(bool)
            mask2 = m2.astype(bool)
            inter = np.logical_and(mask1, mask2).sum()
            if inter <= 0:
                return 0.0
            union = np.logical_or(mask1, mask2).sum()
            if union <= 0:
                return 0.0
            return float(inter) / float(union)
        except Exception:
            # in caso di problemi, fallback alle box
            pass

    # Fallback: IoU sulle bounding box
    x1, y1, x2, y2 = b1
    x1b, y1b, x2b, y2b = b2

    ix1 = max(x1, x1b)
    iy1 = max(y1, y1b)
    ix2 = min(x2, x2b)
    iy2 = min(y2, y2b)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0

    area1 = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
    area2 = max(0.0, (x2b - x1b)) * max(0.0, (y2b - y1b))
    union = area1 + area2 - inter
    if union <= 0:
        return 0.0
    return inter / union


def mask_intersection(
    mask1: np.ndarray, mask2: np.ndarray,
    bbox1, bbox2, 
    vehicle1: Optional[Dict] = None, 
    vehicle2: Optional[Dict] = None,
    last_state: Optional[Dict] = None,
    previous_distances: Optional[Dict] = None,
    enable_perspective_filter: bool = True,
    min_overlap_ratio: float = 0.01,
    min_mask_iou: float = 0.005,
    approach_rate_threshold: float = 0.12,
    distance_increase_threshold: float = 1.02,
    size_ratio_threshold: float = 0.5,
    y_position_threshold: float = 0.3,
    intersection_ratio_threshold: float = 0.15,
    MOVING: str = "MOVING",
    PARKED: str = "PARKED",
) -> bool:
    """
    Verifica se due maschere di segmentazione si intersecano significativamente.
    Applica morphology operations, calcola overlap_ratio e mask_iou, e filtra prospettiva se necessario.
    """
    try:
        # Morphology kernels per smoothing
        kernel = np.ones((3, 3), np.uint8)

        # Converti maschere in binario se necessario
        if mask1.dtype != np.uint8:
            mask1_binary = (mask1 > 0.5).astype(np.uint8)
        else:
            mask1_binary = (mask1 > 0).astype(np.uint8)
        
        if mask2.dtype != np.uint8:
            mask2_binary = (mask2 > 0.5).astype(np.uint8)
        else:
            mask2_binary = (mask2 > 0).astype(np.uint8)

        # Smoothing leggero delle maschere
        mask1_binary = cv2.morphologyEx(mask1_binary, cv2.MORPH_OPEN, kernel, iterations=1)
        mask1_binary = cv2.morphologyEx(mask1_binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        mask2_binary = cv2.morphologyEx(mask2_binary, cv2.MORPH_OPEN, kernel, iterations=1)
        mask2_binary = cv2.morphologyEx(mask2_binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        # Calcola intersezione diretta
        intersection = np.logical_and(mask1_binary > 0, mask2_binary > 0)
        intersection_area = np.sum(intersection)
        
        if intersection_area == 0:
            return False
        
        # Calcola area minima tra le due maschere
        area1 = np.sum(mask1_binary > 0)
        area2 = np.sum(mask2_binary > 0)
        min_area = min(area1, area2)
        
        if min_area == 0:
            return False
        
        # Verifica se l'intersezione supera la soglia
        overlap_ratio = intersection_area / min_area if min_area > 0 else 0
        if overlap_ratio < min_overlap_ratio:
            return False
        
        # Filtro su IoU delle maschere
        union_area = area1 + area2 - intersection_area
        if union_area <= 0:
            return False
        mask_iou = intersection_area / union_area
        if mask_iou < min_mask_iou:
            return False

        # Filtra sovrapposizioni prospettiche se abilitato
        # MA NON filtrare se uno dei veicoli si muove (potrebbe essere impatto)
        if enable_perspective_filter and vehicle1 is not None and vehicle2 is not None:
            track_id1 = vehicle1.get("track_id")
            track_id2 = vehicle2.get("track_id")
            camera_id = vehicle1.get("camera_id", "")
            # Usa stati dal sistema
            if last_state:
                cam_last_state = last_state.get(camera_id, {})
                state1 = cam_last_state.get(track_id1, MOVING)
                state2 = cam_last_state.get(track_id2, MOVING)
            else:
                state1 = state2 = MOVING
                
            # Se almeno uno si muove, NON filtrare come prospettiva (potrebbe essere impatto)
            if state1 == MOVING or state2 == MOVING:
                pass  # Non applicare filtro prospettiva
            else:
                # Solo se entrambi fermi, applica filtro prospettiva
                if is_perspective_overlap(
                    vehicle1, vehicle2, intersection_area, area1, area2,
                    previous_distances, approach_rate_threshold, distance_increase_threshold,
                    size_ratio_threshold, y_position_threshold, intersection_ratio_threshold
                ):
                    return False  # Probabilmente solo prospettiva, non collisione
        
        return True
        
    except Exception as e:
        # In caso di errore, usa bounding box come fallback
        return bbox_intersect(bbox1, bbox2)


def is_perspective_overlap(
    vehicle1: Dict, vehicle2: Dict, 
    intersection_area: float, area1: float, area2: float,
    previous_distances: Optional[Dict] = None,
    approach_rate_threshold: float = 0.12,
    distance_increase_threshold: float = 1.02,
    size_ratio_threshold: float = 0.5,
    y_position_threshold: float = 0.3,
    intersection_ratio_threshold: float = 0.15,
) -> bool:
    """
    Verifica se la sovrapposizione è probabilmente solo prospettiva.
    Returns: True se è probabilmente prospettiva, False se potrebbe essere collisione reale
    """
    bbox1 = vehicle1.get("bbox")
    bbox2 = vehicle2.get("bbox")
    if not bbox1 or not bbox2:
        return False
    
    # 1. Analisi dimensione relativa
    size1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    size2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    size_ratio = min(size1, size2) / max(size1, size2) if max(size1, size2) > 0 else 0
    
    if size_ratio < size_ratio_threshold:
        return True
    
    # 2. Analisi posizione verticale
    center_y1 = (bbox1[1] + bbox1[3]) / 2
    center_y2 = (bbox2[1] + bbox2[3]) / 2
    y_diff = abs(center_y1 - center_y2)
    avg_height = ((bbox1[3] - bbox1[1]) + (bbox2[3] - bbox2[1])) / 2
    
    if y_diff > y_position_threshold * avg_height:
        if size_ratio < 0.7:
            return True
    
    # 3. Analisi area intersezione vs area totale
    total_area = area1 + area2 - intersection_area
    intersection_ratio = intersection_area / total_area if total_area > 0 else 0
    
    if intersection_ratio < intersection_ratio_threshold:
        return True
    
    # 4. Analisi allineamento orizzontale
    center_x1 = (bbox1[0] + bbox1[2]) / 2
    center_x2 = (bbox2[0] + bbox2[2]) / 2
    x_diff = abs(center_x1 - center_x2)
    avg_width = ((bbox1[2] - bbox1[0]) + (bbox2[2] - bbox2[0])) / 2
    
    if x_diff < avg_width * 0.3 and y_diff > avg_height * 0.2:
        return True
    
    # 5. Analisi traiettoria migliorata (con approach_rate)
    track_id1 = vehicle1.get("track_id")
    track_id2 = vehicle2.get("track_id")
    camera_id = vehicle1.get("camera_id", "")
    
    if track_id1 is not None and track_id2 is not None and previous_distances:
        # Crea pair_key inline per evitare import circolare
        pair_key_val = (camera_id, min(track_id1, track_id2), max(track_id1, track_id2))
        curr_center1 = ((bbox1[0] + bbox1[2]) / 2, (bbox1[1] + bbox1[3]) / 2)
        curr_center2 = ((bbox2[0] + bbox2[2]) / 2, (bbox2[1] + bbox2[3]) / 2)
        curr_dist = math.hypot(curr_center1[0] - curr_center2[0], curr_center1[1] - curr_center2[1])
        
        if pair_key_val in previous_distances:
            prev_dist = previous_distances[pair_key_val]
            
            # CRITICO: Calcola velocità di avvicinamento
            distance_change = curr_dist - prev_dist
            approach_rate = -distance_change / prev_dist if prev_dist > 0 else 0
            
            # Se si stanno AVVICINANDO RAPIDAMENTE (> threshold%), è probabilmente una COLLISIONE REALE
            if approach_rate > approach_rate_threshold:
                previous_distances[pair_key_val] = curr_dist
                return False  # NON filtrare, è probabile collisione reale
            
            # Se si stanno allontanando, non è una collisione
            if curr_dist > prev_dist * distance_increase_threshold:
                previous_distances[pair_key_val] = curr_dist
                return True  # Filtra come prospettiva
    
    return False


def get_ground_point(bbox) -> Tuple[float, float]:
    """
    Calcola il punto di contatto a terra (ground point) di un veicolo.
    Il ground point è il centro del bordo inferiore della bounding box.
    
    Args:
        bbox: (x1, y1, x2, y2) formato bounding box
    Returns:
        (x, y) coordinate del ground point
    """
    x1, y1, x2, y2 = bbox
    ground_x = (x1 + x2) / 2.0
    ground_y = float(y2)  # Bordo inferiore
    return (ground_x, ground_y)


def get_bottom_strip_bbox(bbox, height_ratio: float = 0.15) -> Tuple[float, float, float, float]:
    """
    Estrae la striscia inferiore di una bounding box.
    
    Args:
        bbox: (x1, y1, x2, y2) formato bounding box
        height_ratio: Percentuale di altezza da considerare (default 0.15 = 15%)
    Returns:
        (x1, y1_strip, x2, y2) bounding box della striscia inferiore
    """
    x1, y1, x2, y2 = bbox
    height = y2 - y1
    strip_height = height * height_ratio
    y1_strip = y2 - strip_height  # Inizia dalla parte inferiore
    return (x1, y1_strip, x2, y2)


def get_bottom_strip_mask(mask: np.ndarray, bbox, height_ratio: float = 0.15) -> np.ndarray:
    """
    Estrae la striscia inferiore di una maschera.
    
    Args:
        mask: Maschera binaria [H, W]
        bbox: (x1, y1, x2, y2) formato bounding box
        height_ratio: Percentuale di altezza da considerare (default 0.15 = 15%)
    Returns:
        Maschera della striscia inferiore
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    height = y2 - y1
    strip_height = int(height * height_ratio)
    y1_strip = y2 - strip_height
    
    # Crea maschera vuota della stessa dimensione
    strip_mask = np.zeros_like(mask, dtype=bool)
    
    # Estrai solo la parte inferiore
    if y1_strip >= 0 and y1_strip < mask.shape[0]:
        y1_clipped = max(0, y1_strip)
        y2_clipped = min(mask.shape[0], y2)
        strip_mask[y1_clipped:y2_clipped, :] = mask[y1_clipped:y2_clipped, :]
    
    return strip_mask


def ground_point_distance(bbox1, bbox2) -> float:
    """
    Calcola la distanza tra i ground point di due veicoli.
    
    Args:
        bbox1, bbox2: (x1, y1, x2, y2) formato bounding box
    Returns:
        Distanza in pixel tra i ground point
    """
    gp1 = get_ground_point(bbox1)
    gp2 = get_ground_point(bbox2)
    return math.hypot(gp1[0] - gp2[0], gp1[1] - gp2[1])


def bottom_strip_intersection(
    mask1: Optional[np.ndarray], mask2: Optional[np.ndarray],
    bbox1, bbox2,
    height_ratio: float = 0.15,
    min_overlap_ratio: float = 0.01,
) -> bool:
    """
    Verifica se le strisce inferiori di due veicoli si sovrappongono significativamente.
    
    Args:
        mask1, mask2: Maschere opzionali (se None, usa solo bbox)
        bbox1, bbox2: (x1, y1, x2, y2) formato bounding box
        height_ratio: Percentuale di altezza da considerare (default 0.15 = 15%)
        min_overlap_ratio: Soglia minima di overlap per considerare contatto
    Returns:
        True se le strisce inferiori si sovrappongono significativamente
    """
    # Se abbiamo maschere, usa quelle
    if mask1 is not None and mask2 is not None:
        try:
            strip1 = get_bottom_strip_mask(mask1, bbox1, height_ratio)
            strip2 = get_bottom_strip_mask(mask2, bbox2, height_ratio)
            
            intersection = np.logical_and(strip1, strip2).sum()
            if intersection == 0:
                return False
            
            min_area = min(strip1.sum(), strip2.sum())
            if min_area == 0:
                return False
            
            overlap_ratio = intersection / min_area
            return overlap_ratio >= min_overlap_ratio
        except Exception:
            # Fallback a bbox se maschere falliscono
            pass
    
    # Fallback: usa solo bbox delle strisce inferiori
    strip1_bbox = get_bottom_strip_bbox(bbox1, height_ratio)
    strip2_bbox = get_bottom_strip_bbox(bbox2, height_ratio)
    
    # Verifica intersezione bbox
    if not bbox_intersect(strip1_bbox, strip2_bbox):
        return False
    
    # Calcola overlap area
    x1_1, y1_1, x2_1, y2_1 = strip1_bbox
    x1_2, y1_2, x2_2, y2_2 = strip2_bbox
    
    ix1 = max(x1_1, x1_2)
    iy1 = max(y1_1, y1_2)
    ix2 = min(x2_1, x2_2)
    iy2 = min(y2_1, y2_2)
    
    inter_area = max(0.0, (ix2 - ix1)) * max(0.0, (iy2 - iy1))
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
    min_area = min(area1, area2)
    
    if min_area == 0:
        return False
    
    overlap_ratio = inter_area / min_area
    return overlap_ratio >= min_overlap_ratio
