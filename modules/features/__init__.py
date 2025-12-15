"""Moduli di funzionalità opzionali."""

from .ocr_module import OCRModule
from .collision_module import CollisionModule
from .person_safety_module import PersonSafetyDetector
from .person_vehicle_interaction_module import PersonVehicleInteractionDetector
from .person_wall_writing_module import PersonWallWritingDetector

__all__ = ["OCRModule", "CollisionModule", "PersonSafetyDetector", "PersonVehicleInteractionDetector", "PersonWallWritingDetector"]

