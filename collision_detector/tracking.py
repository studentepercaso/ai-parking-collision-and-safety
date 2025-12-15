"""Tracking velocità e traiettoria per collision detector."""

from collections import deque
from typing import Tuple


def before_after_speed_and_dir(hist: deque) -> Tuple[float, float, float]:
    """
    Calcola velocità media "prima" e "dopo" (metà history) e variazione direzione in gradi.
    """
    import math
    
    if len(hist) < 3:
        return 0.0, 0.0, 0.0

    mid = len(hist) // 2
    first_half = list(hist)[:mid]
    second_half = list(hist)[mid:]

    def avg_speed(part):
        if len(part) < 2:
            return 0.0
        dists = [math.hypot(part[i][1] - part[i-1][1], part[i][2] - part[i-1][2]) 
                for i in range(1, len(part))]
        return sum(dists) / len(dists) if dists else 0.0

    v_before = avg_speed(first_half)
    v_after = avg_speed(second_half)

    def avg_vec(part):
        return ((part[-1][1] - part[0][1], part[-1][2] - part[0][2]) 
               if len(part) >= 2 else (0.0, 0.0))

    vx1, vy1 = avg_vec(first_half)
    vx2, vy2 = avg_vec(second_half)

    def angle(dx, dy):
        return math.degrees(math.atan2(dy, dx)) if (dx, dy) != (0, 0) else None

    a1, a2 = angle(vx1, vy1), angle(vx2, vy2)
    if a1 is None or a2 is None:
        dir_change = 0.0
    else:
        diff = abs(a2 - a1)
        dir_change = 360.0 - diff if diff > 180.0 else diff

    return v_before, v_after, dir_change

