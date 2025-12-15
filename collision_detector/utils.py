"""Utility geometriche per collision detector."""

from typing import List, Tuple
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image
import cv2


def point_in_polygon(x: float, y: float, polygon: List[List[int]]) -> bool:
    """Controlla se un punto è dentro un poligono (ray casting algorithm)."""
    n = len(polygon)
    if n < 3:
        return False
    
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (yj != yi) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def base64_to_mask(data: str, shape: Tuple[int, int]) -> np.ndarray:
    """Converte stringa base64 in maschera numpy."""
    img_data = base64.b64decode(data)
    pil_img = Image.open(io.BytesIO(img_data))
    mask = np.array(pil_img.convert("L")) > 127
    if mask.shape != shape:
        mask = cv2.resize(mask.astype(np.uint8), (shape[1], shape[0])).astype(bool)
    return mask

