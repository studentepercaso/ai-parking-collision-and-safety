"""YOLO Module - Caricamento lazy del modello YOLO."""

from typing import Optional, Any, Dict
import gc


class YOLOModule:
    """Gestisce caricamento lazy e caching del modello YOLO."""
    
    _model: Optional[Any] = None
    _model_name: Optional[str] = None
    
    # Configurazione modelli per funzionalità
    MODEL_PRESETS = {
        "minimal": "yolo11n.pt",           # Solo visualizzazione
        "tracking": "yolo11n.pt",          # Tracking base
        "plates": "yolo11s.pt",            # Lettura targhe (più accurato)
        "collision": "yolo11n-seg.pt",     # Collision detection (serve segmentazione)
        "person_safety": "yolo11n.pt",     # Person safety (nano basta)
        "balanced": "yolo11s.pt",          # Bilanciato velocità/accuratezza
        "accurate": "yolo11m.pt",          # Accuratezza alta
    }
    
    @classmethod
    def get_optimal_model(cls, features: Dict[str, bool]) -> str:
        """
        Seleziona modello ottimale in base alle funzionalità richieste.
        
        Args:
            features: Dict con funzionalità abilitate:
                - enable_plates: bool
                - enable_collision: bool
                - enable_person_safety: bool
                - enable_yolo: bool (tracking base)
        
        Returns:
            Nome modello ottimale
        """
        # Priorità: collision > plates > person_safety > tracking
        if features.get("enable_collision", False):
            return cls.MODEL_PRESETS["collision"]  # Serve segmentazione
        
        if features.get("enable_plates", False):
            return cls.MODEL_PRESETS["plates"]  # Più accurato per OCR
        
        if features.get("enable_person_safety", False):
            return cls.MODEL_PRESETS["person_safety"]  # Nano basta
        
        if features.get("enable_yolo", False):
            return cls.MODEL_PRESETS["tracking"]  # Tracking base
        
        return cls.MODEL_PRESETS["minimal"]  # Default: più leggero

    @classmethod
    def get_model(cls, model_name: str = "yolo11n.pt"):
        """
        Carica modello YOLO solo se necessario (lazy loading).
        
        Args:
            model_name: Nome del modello YOLO (es. "yolo11n.pt", "yolo11n-seg.pt")
            
        Returns:
            Modello YOLO o None se errore
        """
        # Se il modello è già caricato e corrisponde, restituiscilo
        if cls._model is not None and cls._model_name == model_name:
            return cls._model
        
        # Carica nuovo modello
        try:
            from ultralytics import YOLO
        except ImportError:
            print(
                "Errore: il pacchetto 'ultralytics' non è installato.\n"
                "Installa prima il pacchetto con:\n"
                "    pip install ultralytics"
            )
            return None
        
        try:
            print(f"[YOLO Module] Caricamento modello: {model_name}")
            cls._model = YOLO(model_name)
            cls._model_name = model_name
            print(f"[YOLO Module] ✅ Modello caricato con successo")
            return cls._model
        except Exception as e:
            print(f"[YOLO Module] ❌ Errore caricamento modello '{model_name}': {e}")
            import traceback
            traceback.print_exc()
            cls._model = None
            cls._model_name = None
            return None
    
    @classmethod
    def is_loaded(cls) -> bool:
        """Verifica se un modello è già caricato."""
        return cls._model is not None
    
    @classmethod
    def get_loaded_model_name(cls) -> Optional[str]:
        """Restituisce il nome del modello attualmente caricato."""
        return cls._model_name
    
    @classmethod
    def unload(cls):
        """
        Scarica il modello per liberare memoria.
        Utile quando si vuole passare a modalità solo visualizzazione.
        """
        if cls._model is not None:
            print(f"[YOLO Module] Scaricamento modello: {cls._model_name}")
            cls._model = None
            cls._model_name = None
            gc.collect()  # Forza garbage collection
            print("[YOLO Module] ✅ Memoria liberata")
