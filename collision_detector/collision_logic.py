"""Logica di classificazione collisioni (major/minor)."""

from collections import deque
from typing import Dict


def is_major_collision(
    v1_before: float,
    v1_after: float,
    v2_before: float,
    v2_after: float,
    dir1_change: float,
    dir2_change: float,
    speed_moving_threshold: float,
    speed_drop_factor: float,
) -> bool:
    """Determina se una collisione è major."""
    # Almeno uno in movimento prima
    if not (v1_before >= speed_moving_threshold or v2_before >= speed_moving_threshold):
        return False
    # Calo netto di velocità o cambio brusco direzione
    return ((v1_before > 0 and v1_after < speed_drop_factor * v1_before) or
            (v2_before > 0 and v2_after < speed_drop_factor * v2_before) or
            dir1_change > 45.0 or dir2_change > 45.0)


def is_minor_collision(
    state1: str,
    state2: str,
    hist1: deque,
    hist2: deque,
    speed1: float,
    speed2: float,
    MOVING: str,
    PARKED: str,
    NUDGE_DISTANCE: float,
    SPEED_PARKED_THRESHOLD: float,
) -> bool:
    """Determina se una collisione è minor."""
    import math
    
    # Caso: A moving, B parked (o viceversa)
    if not ((state1 == MOVING and state2 == PARKED) or 
            (state2 == MOVING and state1 == PARKED)):
        return False

    # L'auto PARKED si muove di poco dopo il contatto
    parked_hist = hist2 if state2 == PARKED else hist1
    parked_speed = speed2 if state2 == PARKED else speed1
    
    if len(parked_hist) < 2:
        return False
    
    # Controllo 1: Spostamento totale
    x0, y0 = parked_hist[0][1], parked_hist[0][2]
    x1, y1 = parked_hist[-1][1], parked_hist[-1][2]
    if math.hypot(x1 - x0, y1 - y0) >= NUDGE_DISTANCE:
        return True
    
    # Controllo 2: Movimento recente (ultimi 2-3 frame)
    if len(parked_hist) >= 3:
        x_recent, y_recent = parked_hist[-3][1], parked_hist[-3][2]
        if math.hypot(x1 - x_recent, y1 - y_recent) >= (NUDGE_DISTANCE * 0.5):
            return True
    
    # Controllo 3: Velocità aumentata
    return parked_speed > SPEED_PARKED_THRESHOLD * 2

