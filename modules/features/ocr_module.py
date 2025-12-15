"""OCR Module - Lettura targhe con EasyOCR (lazy loading)."""

from typing import Optional, Dict, Tuple, Any, List
import numpy as np


class OCRModule:
    """Gestisce caricamento lazy e caching del reader OCR."""
    
    _reader: Optional[Any] = None
    _config: Dict[str, Any] = {}
    
    @classmethod
    def get_reader(cls, languages: List[str] = None, use_gpu: bool = False, quantize: bool = True):
        """
        Carica reader EasyOCR solo se necessario (lazy loading) con configurazione ottimizzata.
        
        Args:
            languages: Lista lingue (default: ['en'] - più leggero)
            use_gpu: Usa GPU se disponibile (default: False)
            quantize: Usa quantizzazione per ridurre memoria (default: True)
            
        Returns:
            Reader EasyOCR o None se errore
        """
        # Default languages
        if languages is None:
            languages = ['en']
            
        current_config = {
            "languages": sorted(languages),
            "use_gpu": use_gpu,
            "quantize": quantize
        }
        
        # Se già caricato e config è uguale (o compatibile), restituisci
        if cls._reader is not None:
            # Se la richiesta è compatibile (stesse lingue o subset già caricato)
            # Per semplicità, ricarichiamo solo se la config cambia esplicitamente
            if cls._config == current_config:
                return cls._reader
            else:
                print(f"[OCR Module] Cambio configurazione OCR: {cls._config} -> {current_config}")
                cls.unload()
        
        try:
            import easyocr
        except ImportError:
            print(
                "Avviso: EasyOCR non è installato. La lettura targhe sarà disabilitata.\n"
                "Installa con: pip install easyocr"
            )
            return None
        
        try:
            print(f"[OCR Module] Caricamento EasyOCR (lingue: {languages}, gpu={use_gpu}, quantize={quantize})...")
            # Configurazione ottimizzata
            cls._reader = easyocr.Reader(
                languages,
                gpu=use_gpu,
                quantize=quantize,
                model_storage_directory=None,  # Usa cache globale default
                download_enabled=True
            )
            cls._config = current_config
            print("[OCR Module] ✅ EasyOCR caricato con successo")
            return cls._reader
        except Exception as e:
            print(f"[OCR Module] ❌ Errore caricamento EasyOCR: {e}")
            cls._reader = None
            cls._config = {}
            return None
    
    @classmethod
    def is_loaded(cls) -> bool:
        """Verifica se il reader è già caricato."""
        return cls._reader is not None
    
    @classmethod
    def unload(cls):
        """Scarica il reader per liberare memoria."""
        if cls._reader is not None:
            print("[OCR Module] Scaricamento EasyOCR")
            cls._reader = None
            cls._config = {}
            import gc
            gc.collect()


class LicensePlateManager:
    """Gestisce lettura e caching delle targhe con tentativi multipli."""
    
    def __init__(self, ocr_reader, max_attempts: int = 5, frames_between: int = 10):
        """
        Args:
            ocr_reader: Reader EasyOCR (o None se disabilitato)
            max_attempts: Numero massimo tentativi per leggere una targa
            frames_between: Frame minimi tra un tentativo e l'altro
        """
        self.ocr_reader = ocr_reader
        self.plate_cache: Dict[int, str] = {}  # ID -> targa
        self.attempts: Dict[int, int] = {}  # ID -> numero tentativi
        self.car_sizes: Dict[int, float] = {}  # ID -> area bbox
        self.last_attempt_frame: Dict[int, int] = {}  # ID -> ultimo frame tentativo
        self.max_attempts = max_attempts
        self.frames_between = frames_between
        self.enabled = ocr_reader is not None
    
    def get_or_read_plate(
        self, frame: np.ndarray, car_bbox: Tuple[int, int, int, int], track_id: int, frame_count: int
    ) -> Optional[str]:
        """
        Restituisce targa dalla cache o tenta di leggerla.
        
        Args:
            frame: Frame del video
            car_bbox: Bounding box dell'auto (x1, y1, x2, y2)
            track_id: ID tracciato dell'auto
            frame_count: Numero frame corrente
            
        Returns:
            Testo targa o None
        """
        if not self.enabled:
            return None
        
        # Se già in cache, restituisci
        if track_id in self.plate_cache:
            return self.plate_cache[track_id]
        
        # Calcola dimensione auto
        x1, y1, x2, y2 = car_bbox
        car_area = (x2 - x1) * (y2 - y1)
        
        # Controlla se dobbiamo provare
        attempts = self.attempts.get(track_id, 0)
        last_frame = self.last_attempt_frame.get(track_id, -999)
        frames_since_last = frame_count - last_frame
        
        if attempts >= self.max_attempts:
            return None  # Troppi tentativi falliti
        
        if frames_since_last < self.frames_between:
            return None  # Troppo presto per riprovare
        
        # Estrai regione targa (parte inferiore del bbox)
        h = y2 - y1
        plate_y1 = max(0, y1 + int(h * 0.6))  # Ultimi 40% dell'altezza
        plate_y2 = y2
        plate_roi = frame[plate_y1:plate_y2, x1:x2]
        
        if plate_roi.size == 0:
            return None
        
        # Prova a leggere
        try:
            results = self.ocr_reader.readtext(plate_roi)
            if results:
                # Prendi il risultato con confidenza più alta
                best = max(results, key=lambda x: x[2])
                plate_text = best[1].strip().upper()
                # Filtra caratteri validi (lettere, numeri, spazi)
                plate_text = ''.join(c for c in plate_text if c.isalnum() or c.isspace())
                if len(plate_text) >= 4:  # Targa valida almeno 4 caratteri
                    self.plate_cache[track_id] = plate_text
                    self.attempts[track_id] = attempts + 1
                    self.last_attempt_frame[track_id] = frame_count
                    return plate_text
        except Exception as e:
            print(f"[LicensePlateManager] Errore lettura targa: {e}")
        
        # Aggiorna contatori
        self.attempts[track_id] = attempts + 1
        self.last_attempt_frame[track_id] = frame_count
        self.car_sizes[track_id] = car_area
        
        return None
