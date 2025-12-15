"""Caricamento configurazioni per collision detector."""

from pathlib import Path
import json

ZONES_CONFIG_FILE = Path("zones_config.json")
COLLISION_CONFIG_FILE = Path("collision_config.json")


def load_zones_config() -> dict:
    """Carica configurazione zone."""
    if ZONES_CONFIG_FILE.exists():
        with open(ZONES_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_collision_config() -> dict:
    """Carica configurazione collision detector da file JSON."""
    if COLLISION_CONFIG_FILE.exists():
        try:
            with open(COLLISION_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config
        except Exception as e:
            print(f"⚠️  Errore caricamento {COLLISION_CONFIG_FILE}: {e}. Uso parametri default.")
    # Defaults estesi per sicurezza persone
    return {
        "enable_person_safety": True,
        "enable_person_loitering": True,
        "enable_person_fall": True,
        "LOITER_SECONDS": 20.0,
        "LOITER_RADIUS": 120.0,
        "FALL_ASPECT_RATIO": 0.55,
        "FALL_SPEED_DROP": 0.45,
        "FALL_MIN_HEIGHT": 40.0,
    }

