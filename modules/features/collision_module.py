"""Collision Module - Rilevamento collisioni veicoli (senza person safety)."""

from typing import Optional, Callable, Dict, Any
from pathlib import Path


class CollisionModule:
    """Gestisce creazione e configurazione di CollisionDetector."""
    
    @staticmethod
    def create_detector(
        on_event: Optional[Callable[[Dict], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        collision_config_path: Optional[Path] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Crea CollisionDetector solo quando necessario.
        
        Args:
            on_event: Callback per eventi collisione
            log_callback: Callback per logging
            collision_config_path: Path a file configurazione collisioni
            **kwargs: Parametri aggiuntivi per CollisionDetector
            
        Returns:
            CollisionDetector istanza o None se errore
        """
        try:
            from collision_detector import CollisionDetector
        except ImportError:
            print("[Collision Module] ❌ collision_detector non trovato")
            return None
        
        try:
            print("[Collision Module] Creazione CollisionDetector...")
            detector = CollisionDetector(
                on_event=on_event,
                log_callback=log_callback,
                collision_config_path=collision_config_path,
                **kwargs
            )
            print("[Collision Module] ✅ CollisionDetector creato")
            return detector
        except Exception as e:
            print(f"[Collision Module] ❌ Errore creazione CollisionDetector: {e}")
            import traceback
            traceback.print_exc()
            return None

