"""Frame Buffer - Gestione buffer video thread-safe."""

import cv2
import threading
import queue
import time
from typing import Optional, Tuple
import numpy as np

class FrameBuffer:
    """
    Buffer di frame con thread dedicato per la lettura.
    Mantiene sempre gli ultimi N frame disponibili, scartando i più vecchi se il buffer è pieno.
    Utile per streaming RTSP per evitare latenza e buffer bloat.
    """
    
    def __init__(self, cap: cv2.VideoCapture, maxsize: int = 5):
        """
        Inizializza il frame buffer.
        
        Args:
            cap: VideoCapture object da cui leggere i frame
            maxsize: Dimensione massima del buffer (default 5 frame)
        """
        self.cap = cap
        self.maxsize = maxsize
        self.frame_queue = queue.Queue(maxsize=maxsize)
        self.running = False
        self.read_thread = None
        self.lock = threading.Lock()
        self.last_frame = None
        self.last_frame_time = None
        
    def start(self):
        """Avvia il thread di lettura frame."""
        if self.running:
            return
        
        self.running = True
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        print(f"[FrameBuffer] Thread di lettura avviato (buffer size: {self.maxsize})")
        
    def stop(self):
        """Ferma il thread di lettura."""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
            print("[FrameBuffer] Thread di lettura fermato")
            
    def _read_loop(self):
        """Loop di lettura frame in thread separato."""
        consecutive_failures = 0
        max_failures = 50  # Max frame persi consecutivi prima di fermarsi
        
        while self.running:
            try:
                ret, frame = self.cap.read()
                
                if not ret or frame is None:
                    consecutive_failures += 1
                    # Se abbiamo fallito troppi tentativi consecutivi, il video è probabilmente finito o stream caduto
                    if consecutive_failures >= max_failures:
                        print(f"[FrameBuffer] Stream interrotto dopo {consecutive_failures} tentativi falliti")
                        # Non fermiamo self.running qui per permettere riconnessioni esterne se necessario,
                        # ma rallentiamo il loop
                        time.sleep(0.5)
                        continue
                    
                    time.sleep(0.01)
                    continue
                
                # Reset contatore se abbiamo letto un frame valido
                consecutive_failures = 0
                
                # Se la queue è piena, rimuovi il frame più vecchio per fare spazio al nuovo (LIFO-ish logic for display)
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                
                # Aggiungi il nuovo frame
                try:
                    self.frame_queue.put_nowait((frame.copy(), time.time()))
                except queue.Full:
                    pass
                    
            except Exception as e:
                print(f"[FrameBuffer] Errore lettura frame: {e}")
                time.sleep(0.1)
    
    def read(self) -> Optional[Tuple[np.ndarray, float]]:
        """
        Restituisce l'ultimo frame disponibile.
        
        Returns:
            Tuple (frame, timestamp) oppure None se non ci sono frame disponibili
        """
        # Prendi tutti i frame disponibili e mantieni solo l'ultimo per avere la minima latenza
        latest_frame = None
        latest_timestamp = None
        
        while not self.frame_queue.empty():
            try:
                latest_frame, latest_timestamp = self.frame_queue.get_nowait()
            except queue.Empty:
                break
        
        if latest_frame is not None:
            self.last_frame = latest_frame
            self.last_frame_time = latest_timestamp
        
        if latest_frame is not None:
            return (latest_frame, latest_timestamp)
        elif self.last_frame is not None:
            # Se non ci sono frame nuovi, restituisci l'ultimo valido (congelamento immagine invece di nero)
            return (self.last_frame, self.last_frame_time)
        else:
            return None
    
    def is_running(self) -> bool:
        """Verifica se il thread di lettura è attivo."""
        return self.running
    
    def get_queue_size(self) -> int:
        """Restituisce il numero di frame attualmente nel buffer."""
        return self.frame_queue.qsize()

