from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable, Any
import argparse
import threading
import time
import re
import json
import csv
import queue
import sys
from datetime import datetime
from collections import deque
from urllib.parse import quote
import cv2
import numpy as np

from collision_detector import CollisionDetector

# Import moduli core (per type hints e uso globale)
from modules.core.statistics import StatisticsCollector
from modules.utils.frame_buffer import FrameBuffer


# ============================================================================
# CONFIGURAZIONE RTSP - Telecamere Hikvision
# ============================================================================
# Carica configurazione RTSP da file (evita password hardcoded)
RTSP_CONFIG_FILE = Path("config/rtsp.json")
RTSP_CONFIG_TEMPLATE = Path("rtsp_config.json.template")

def _load_rtsp_config():
    """Carica configurazione RTSP da file JSON."""
    defaults = {
        "ip": "192.168.1.124",
        "port": "554",
        "user": "User",
        "password": ""  # Deve essere configurato nel file
    }
    
    # Prova a caricare da config/rtsp.json
    if RTSP_CONFIG_FILE.exists():
        try:
            with open(RTSP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return {**defaults, **config}
        except Exception as e:
            print(f"⚠️  Errore caricamento {RTSP_CONFIG_FILE}: {e}")
            print(f"   Usa i valori di default. Crea {RTSP_CONFIG_TEMPLATE} come template.")
    
    # Se non esiste, usa default (password vuota)
    print(f"⚠️  File {RTSP_CONFIG_FILE} non trovato.")
    print(f"   Copia {RTSP_CONFIG_TEMPLATE} come {RTSP_CONFIG_FILE} e inserisci le tue credenziali.")
    return defaults

_rtsp_config = _load_rtsp_config()
RTSP_IP = _rtsp_config.get("ip", "192.168.1.124")
RTSP_PORT = _rtsp_config.get("port", "554")
RTSP_USER = _rtsp_config.get("user", "User")
RTSP_PASSWORD = _rtsp_config.get("password", "")

# Verifica che la password sia configurata
if not RTSP_PASSWORD:
    print("⚠️  ATTENZIONE: Password RTSP non configurata!")
    print(f"   Crea {RTSP_CONFIG_FILE} con le tue credenziali (usa {RTSP_CONFIG_TEMPLATE} come template)")

# URL RTSP costruito automaticamente (gestisce caratteri speciali nella password)
RTSP_STREAM_DEFAULT = f"rtsp://{quote(RTSP_USER, safe='')}:{quote(RTSP_PASSWORD, safe='')}@{RTSP_IP}:{RTSP_PORT}/Streaming/Channels/102"

# Formato URL per altre telecamere (puoi crearli così):
# Canale 1 Sub Stream:  /Streaming/Channels/102
# Canale 1 Main Stream: /Streaming/Channels/101
# Canale 2 Sub Stream:  /Streaming/Channels/202
# Canale 2 Main Stream: /Streaming/Channels/201
# ... e così via per altri canali
# ============================================================================

# Cartella per anteprime telecamere (foto salvate durante la scansione)
CAMERA_PREVIEWS_DIR = Path("camera_previews")
CAMERA_PREVIEWS_DIR.mkdir(exist_ok=True)


# Funzioni rimosse: load_yolo_model, load_ocr_reader (ora usano i moduli detection/features)




class DashboardWindow:
    """Finestra dashboard Tkinter con pulsanti e statistiche."""
    
    def __init__(self, stats_collector: StatisticsCollector, log_file: Path = None):
        try:
            import tkinter as tk
            from tkinter import ttk, scrolledtext
            self.tk = tk
            self.ttk = ttk
            self.scrolledtext = scrolledtext
        except ImportError:
            print("Avviso: Tkinter non disponibile. Dashboard disabilitato.")
            self.tk = None
            return
        
        self.stats = stats_collector
        self.log_file = log_file
        self.running = True
        
        # Queue per comunicazione thread-safe
        self.command_queue = queue.Queue()
        
        # Crea finestra
        self.root = self.tk.Tk()
        self.root.title("Dashboard - YOLO Tracking")
        self.root.geometry("600x500")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Tab
        self.notebook = self.ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Tab 1: Statistiche Real-Time
        self.stats_frame = self.tk.Frame(self.notebook)
        self.notebook.add(self.stats_frame, text="Statistiche")
        self._create_stats_tab()
        
        # Tab 2: Eventi
        self.events_frame = self.tk.Frame(self.notebook)
        self.notebook.add(self.events_frame, text="Eventi")
        self._create_events_tab()
        
        # Tab 3: Controlli
        self.controls_frame = self.tk.Frame(self.notebook)
        self.notebook.add(self.controls_frame, text="Controlli")
        self._create_controls_tab()
        
        # Aggiorna ogni 500ms
        self.update_display()
    
    def _create_stats_tab(self):
        """Crea tab statistiche."""
        # FPS
        self.fps_label = self.tk.Label(
            self.stats_frame, text="FPS: --", font=("Arial", 24, "bold"), fg="green"
        )
        self.fps_label.pack(pady=10)
        
        # Oggetti in scena
        self.objects_label = self.tk.Label(
            self.stats_frame, text="Auto: 0 | Persone: 0", font=("Arial", 18)
        )
        self.objects_label.pack(pady=5)
        
        # Totale visti
        self.total_label = self.tk.Label(
            self.stats_frame, text="Totale Auto: 0 | Totale Persone: 0", font=("Arial", 12)
        )
        self.total_label.pack(pady=5)
        
        # Frame processati
        self.frames_label = self.tk.Label(
            self.stats_frame, text="Frame: 0", font=("Arial", 12)
        )
        self.frames_label.pack(pady=5)
        
        # Stato
        self.status_label = self.tk.Label(
            self.stats_frame, text="Stato: STOPPED", font=("Arial", 12, "bold")
        )
        self.status_label.pack(pady=10)
        
        # ID attivi
        self.ids_text = self.scrolledtext.ScrolledText(
            self.stats_frame, height=8, width=50
        )
        self.ids_text.pack(pady=5, fill="both", expand=True)
    
    def _create_events_tab(self):
        """Crea tab eventi."""
        self.events_text = self.scrolledtext.ScrolledText(
            self.events_frame, height=20, width=70
        )
        self.events_text.pack(fill="both", expand=True, padx=5, pady=5)
    
    def _create_controls_tab(self):
        """Crea tab controlli con pulsanti."""
        # Pulsante Pause/Resume
        self.pause_button = self.tk.Button(
            self.controls_frame,
            text="⏸ PAUSE",
            font=("Arial", 14, "bold"),
            bg="#FFA500",
            command=self.toggle_pause,
            width=15,
            height=2,
        )
        self.pause_button.pack(pady=10)
        
        # Pulsante Screenshot
        self.screenshot_button = self.tk.Button(
            self.controls_frame,
            text="📷 SCREENSHOT",
            font=("Arial", 14, "bold"),
            bg="#4CAF50",
            command=self.take_screenshot,
            width=15,
            height=2,
        )
        self.screenshot_button.pack(pady=10)
        
        # Pulsante Stop
        self.stop_button = self.tk.Button(
            self.controls_frame,
            text="⏹ STOP",
            font=("Arial", 14, "bold"),
            bg="#F44336",
            command=self.stop_processing,
            width=15,
            height=2,
        )
        self.stop_button.pack(pady=10)
        
        # Pulsante Apri Log
        if self.log_file:
            self.log_button = self.tk.Button(
                self.controls_frame,
                text="📄 APRI CARTELLA LOG",
                font=("Arial", 12),
                command=self.open_log_folder,
                width=20,
            )
            self.log_button.pack(pady=10)
        
        # Label info
        info_text = (
            "Pulsanti:\n\n"
            "⏸ PAUSE - Mette in pausa/riprende l'elaborazione\n"
            "📷 SCREENSHOT - Salva frame corrente\n"
            "⏹ STOP - Ferma l'elaborazione\n"
            "📄 APRI LOG - Apre cartella log"
        )
        self.info_label = self.tk.Label(
            self.controls_frame, text=info_text, justify="left", font=("Arial", 10)
        )
        self.info_label.pack(pady=10)
    
    def toggle_pause(self):
        """Invia comando pause/resume."""
        self.command_queue.put("pause")
    
    def take_screenshot(self):
        """Invia comando screenshot."""
        self.command_queue.put("screenshot")
    
    def stop_processing(self):
        """Invia comando stop."""
        self.command_queue.put("stop")
        self.on_closing()
    
    def open_log_folder(self):
        """Apre cartella log in modo non bloccante."""
        import os
        import subprocess
        
        if self.log_file and self.log_file.parent.exists():
            # Usa subprocess in modo asincrono per non bloccare
            try:
                path = str(self.log_file.parent.resolve())
                # Windows
                subprocess.Popen(f'explorer "{path}"', shell=True)
                # Per Linux: subprocess.Popen(['xdg-open', path])
                # Per Mac: subprocess.Popen(['open', path])
            except Exception:  # noqa: BLE001
                # Fallback a os.startfile
                try:
                    os.startfile(self.log_file.parent)
                except Exception:  # noqa: BLE001
                    pass
    
    def get_command(self) -> Optional[str]:
        """Restituisce comando dalla queue se disponibile."""
        try:
            return self.command_queue.get_nowait()
        except queue.Empty:
            return None
    
    def update_display(self):
        """Aggiorna display con statistiche correnti."""
        if not self.running:
            return
        
        stats = self.stats.get_stats()
        
        # Aggiorna statistiche
        self.fps_label.config(text=f"FPS: {stats['current_fps']:.1f} (avg: {stats['avg_fps']:.1f})")
        self.objects_label.config(
            text=f"Auto: {stats['current_objects']['cars']} | Persone: {stats['current_objects']['persons']}"
        )
        self.total_label.config(
            text=f"Totale Auto: {stats['total_cars_seen']} | Totale Persone: {stats['total_persons_seen']}"
        )
        self.frames_label.config(text=f"Frame: {stats['frame_count']}")
        
        # Stato con colore
        status_colors = {
            "RUNNING": "green",
            "PAUSED": "orange",
            "STOPPED": "gray",
            "ERROR": "red",
        }
        color = status_colors.get(stats["status"], "black")
        self.status_label.config(text=f"Stato: {stats['status']}", fg=color)
        
        # ID attivi
        self.ids_text.delete("1.0", "end")
        ids_text = "Auto ID attivi: " + ", ".join(str(i) for i in stats["active_track_ids"]["cars"])
        ids_text += "\n\nPersone ID attivi: " + ", ".join(str(i) for i in stats["active_track_ids"]["persons"])
        self.ids_text.insert("1.0", ids_text)
        
        # Eventi
        self.events_text.delete("1.0", "end")
        for event in stats["events"]:
            line = f"[{event['timestamp']}] {event['type']}"
            if event["details"]:
                line += f": {event['details']}"
            if event["track_id"]:
                line += f" (ID: {event['track_id']})"
            self.events_text.insert("end", line + "\n")
        
        # Non usare after() perché non abbiamo mainloop()
        # update_display() verrà chiamato manualmente dal loop principale
    
    def on_closing(self):
        """Gestisce chiusura finestra."""
        self.running = False
        self.root.destroy()
    
    def update(self):
        """Aggiorna dashboard (da chiamare periodicamente nel thread principale)."""
        if self.tk and self.running:
            try:
                self.root.update()
            except Exception:  # noqa: BLE001
                pass  # Finestra chiusa




def analyze_image(image_path: Path, model_name: str = "yolo11n.pt") -> bool:
    """Esegue l'analisi YOLO su una singola immagine. Restituisce True se va a buon fine."""
    if not image_path.is_file():
        print(f"Errore: immagine non trovata -> {image_path.resolve()}")
        return False

    from modules.detection.yolo_module import YOLOModule
    model = YOLOModule.get_model(model_name)
    if model is None:
        print(f"Errore: impossibile caricare il modello YOLO '{model_name}'")
        return False

    try:
        # Esegue la predizione e salva automaticamente i risultati annotati.
        # project/name servono a controllare dove vengono salvate le immagini.
        model.predict(
            source=str(image_path),
            save=True,
            project="runs",
            name="detect",
            exist_ok=True,  # riutilizza la cartella se già esiste
        )
    except Exception as e:  # noqa: BLE001
        print(f"Errore durante l'analisi dell'immagine: {e}")
        return False

    print("Analisi completata con successo.")
    print("Controlla la cartella 'runs/detect' accanto allo script")
    print("per trovare l'immagine annotata (es. 'image0.jpg', 'image1.jpg', ecc.).")
    return True




def extract_license_plate_region(frame: np.ndarray, car_bbox: tuple, region_type: str = "lower") -> Optional[np.ndarray]:
    """
    Estrae diverse regioni della bounding box dell'auto dove potrebbe essere la targa.
    
    Args:
        frame: Frame del video (numpy array BGR)
        car_bbox: Bounding box dell'auto in formato (x1, y1, x2, y2) in pixel
        region_type: Tipo di regione da estrarre:
            - "lower": regione inferiore (65%-100% altezza) - default
            - "lower_wide": regione inferiore più larga (60%-100% altezza)
            - "center_lower": regione centrale-inferiore (50%-85% altezza)
        
    Returns:
        ROI della targa (numpy array) oppure None se la regione è troppo piccola
    """
    x1, y1, x2, y2 = [int(coord) for coord in car_bbox]
    
    # Assicurati che le coordinate siano dentro il frame
    h, w = frame.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    
    car_height = y2 - y1
    car_width = x2 - x1
    
    # Definisci le regioni in base al tipo
    if region_type == "lower":
        # Regione inferiore (65%-100% altezza)
        roi_y1 = y1 + int(car_height * 0.65)
        roi_y2 = y2
        roi_x1 = x1
        roi_x2 = x2
    elif region_type == "lower_wide":
        # Regione inferiore più larga (60%-100% altezza)
        roi_y1 = y1 + int(car_height * 0.60)
        roi_y2 = y2
        roi_x1 = x1
        roi_x2 = x2
    elif region_type == "center_lower":
        # Regione centrale-inferiore (50%-85% altezza)
        roi_y1 = y1 + int(car_height * 0.50)
        roi_y2 = y1 + int(car_height * 0.85)
        roi_x1 = x1
        roi_x2 = x2
    else:
        # Default: lower
        roi_y1 = y1 + int(car_height * 0.65)
        roi_y2 = y2
        roi_x1 = x1
        roi_x2 = x2
    
    roi_height = roi_y2 - roi_y1
    roi_width = roi_x2 - roi_x1
    
    # Se la regione è troppo piccola, non ha senso fare OCR
    if roi_height < 20 or roi_width < 30:
        return None
    
    # Estrai ROI
    roi = frame[roi_y1:roi_y2, roi_x1:roi_x2].copy()
    
    return roi


def validate_italian_plate(text: str, debug: bool = False) -> Optional[str]:
    """
    Valida e formatta una targa italiana.
    Formato: 2 lettere + 3 numeri + 2 lettere (es. AB123CD).
    Accetta anche formati con spazi/trattini: "AB 123 CD", "AB-123-CD", ecc.
    
    Args:
        text: Testo grezzo da OCR
        debug: Se True, stampa info di debug
        
    Returns:
        Targa formattata (es. "AB123CD") oppure None se non valida
    """
    if debug:
        print(f"    [DEBUG] Validazione targa - Testo grezzo: '{text}'")
    
    # Rimuovi spazi, trattini e caratteri non alfanumerici
    text_clean = ''.join(c.upper() for c in text if c.isalnum())
    
    if debug:
        print(f"    [DEBUG] Testo pulito: '{text_clean}' (lunghezza: {len(text_clean)})")
    
    # Lunghezza esatta: 7 caratteri (2 lettere + 3 numeri + 2 lettere)
    if len(text_clean) != 7:
        if debug:
            print(f"    [DEBUG] SCARTATA: lunghezza {len(text_clean)} invece di 7")
        return None
    
    # Verifica formato: lettera, lettera, numero, numero, numero, lettera, lettera
    pattern = r'^[A-Z]{2}[0-9]{3}[A-Z]{2}$'
    if re.match(pattern, text_clean):
        if debug:
            print(f"    [DEBUG] VALIDA: {text_clean}")
        return text_clean
    
    if debug:
        print(f"    [DEBUG] SCARTATA: formato non corrisponde a pattern italiano")
    return None


def try_read_plate_from_regions(frame: np.ndarray, car_bbox: tuple, ocr_reader, debug: bool = False) -> Optional[str]:
    """
    Prova a leggere la targa provando diverse regioni e preprocessing.
    
    Args:
        frame: Frame del video
        car_bbox: Bounding box dell'auto
        ocr_reader: Reader EasyOCR
        debug: Se True, stampa debug
        
    Returns:
        Targa letta o None
    """
    # Lista di regioni da provare (in ordine di probabilità)
    regions_to_try = ["lower", "lower_wide", "center_lower"]
    # Lista di preprocessing da provare
    preprocessing_to_try = ["default", "adaptive", "morphology"]
    
    for region_type in regions_to_try:
        if debug:
            print(f"  [DEBUG] Provando regione: {region_type}")
        
        roi = extract_license_plate_region(frame, car_bbox, region_type=region_type)
        if roi is None:
            if debug:
                print(f"    [DEBUG] ROI troppo piccola, skip")
            continue
        
        for prep_type in preprocessing_to_try:
            if debug:
                print(f"    [DEBUG] Preprocessing: {prep_type}")
            
            plate = read_license_plate(roi, ocr_reader, preprocessing_type=prep_type, debug=debug)
            if plate:
                if debug:
                    print(f"  [DEBUG] Targa trovata con regione '{region_type}' e preprocessing '{prep_type}': {plate}")
                return plate
    
    return None


def read_license_plate(roi: np.ndarray, ocr_reader, preprocessing_type: str = "default", debug: bool = False) -> Optional[str]:
    """
    Legge il testo della targa dalla regione di interesse usando EasyOCR.
    Valida il formato italiano: 2 lettere + 3 numeri + 2 lettere.
    Prova diversi preprocessing se il primo fallisce.
    
    Args:
        roi: Regione di interesse (numpy array BGR)
        ocr_reader: Reader EasyOCR già inizializzato
        preprocessing_type: Tipo di preprocessing ("default", "adaptive", "morphology")
        debug: Se True, stampa info di debug
        
    Returns:
        Targa formattata (es. "AB123CD") oppure None se non valida
    """
    if ocr_reader is None:
        return None
    
    try:
        # Preprocessing migliorato per targhe italiane
        h, w = roi.shape[:2]
        
        if debug:
            print(f"    [DEBUG] OCR - ROI size: {w}x{h}")
        
        # Resize se troppo piccola (targhe italiane sono tipicamente orizzontali)
        min_height, min_width = 60, 140
        if h < min_height or w < min_width:
            scale_h = min_height / h if h < min_height else 1
            scale_w = min_width / w if w < min_width else 1
            scale = max(scale_h, scale_w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            roi = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            if debug:
                print(f"    [DEBUG] OCR - Resized to {new_w}x{new_h}")
        
        # Converti in scala di grigi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Applica preprocessing in base al tipo
        if preprocessing_type == "default":
            # Preprocessing standard: OTSU threshold + CLAHE
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(binary)
        elif preprocessing_type == "adaptive":
            # Preprocessing adattivo: threshold adattivo invece di OTSU
            enhanced = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
        elif preprocessing_type == "morphology":
            # Preprocessing con morfologia: threshold + operazioni morfologiche
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            enhanced = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_OPEN, kernel)
        else:
            # Default: semplice threshold
            _, enhanced = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        roi_enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
        
        # Esegui OCR
        results = ocr_reader.readtext(roi_enhanced, detail=1)
        
        if debug:
            print(f"    [DEBUG] OCR - Risultati trovati: {len(results)}")
            for i, result in enumerate(results):
                if len(result) >= 2:
                    conf = result[2] if len(result) > 2 else 0
                    print(f"      [{i+1}] '{result[1]}' (confidenza: {conf:.2f})")
        
        if not results:
            if debug:
                print(f"    [DEBUG] OCR - Nessun testo rilevato")
            return None
        
        # Prova tutti i risultati, cerca uno che corrisponda al formato italiano
        for result in sorted(results, key=lambda x: x[2] if len(x) > 2 else 0, reverse=True):
            if len(result) >= 2:
                text = result[1].strip()
                validated = validate_italian_plate(text, debug=debug)
                if validated:
                    return validated
        
        # Se nessun risultato corrisponde al formato, prova a correggere errori comuni
        # (es. O->0, I->1, ecc.) sul risultato con confidenza più alta
        best_result = max(results, key=lambda x: x[2] if len(x) > 2 else 0)
        if len(best_result) >= 2:
            text = best_result[1].strip().upper()
            if debug:
                print(f"    [DEBUG] OCR - Tentativo correzione errori su: '{text}'")
            # Sostituzioni comuni per errori OCR
            text_corrected = text.replace('O', '0').replace('I', '1').replace('S', '5').replace('Z', '2')
            text_corrected = ''.join(c for c in text_corrected if c.isalnum())
            
            validated = validate_italian_plate(text_corrected, debug=debug)
            if validated:
                return validated
        
        if debug:
            print(f"    [DEBUG] OCR - Nessuna targa valida trovata")
        return None
    except Exception as e:  # noqa: BLE001
        if debug:
            print(f"    [DEBUG] OCR - Errore: {e}")
        return None


# ============================================================================
# FUNZIONI HELPER COMUNI
# ============================================================================
    
def _get_screen_size() -> Tuple[int, int]:
    """
    Restituisce la dimensione dello schermo (larghezza, altezza) in pixel.
    Usa Tkinter se disponibile, altrimenti un fallback sicuro.
    """
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return int(width), int(height)
    except Exception:  # noqa: BLE001
        # Fallback ragionevole se Tkinter non è disponibile
        return 1280, 720

    
def _run_tracking_on_frame(model, frame, conf: float = 0.6, imgsz: int = 1280, classes=None):
    """
    Esegue tracking YOLO su un singolo frame.
    
    Args:
        model: Modello YOLO caricato
        frame: Frame da analizzare (numpy array BGR)
        conf: Soglia di confidenza (default: 0.6)
        imgsz: Dimensione input (default: 1280)
        classes: Lista di classi da rilevare (None = tutte).
                 Classi COCO: 0=person, 2=car, 3=motorcycle, 5=bus, 7=truck
        
    Returns:
        Lista risultati tracking (può essere vuota)
    """
    # Se classes non specificato, usa default: persona e auto
    if classes is None:
        classes = [0, 2]  # 0 = person, 2 = car
    
    return model.track(
        source=frame,
        tracker="bytetrack.yaml",
        conf=conf,
        imgsz=imgsz,
        iou=0.5,
        classes=classes,
        persist=True,
        verbose=False,
    )


def _draw_stats_overlay(
    frame: np.ndarray,
    stats_data: Dict,
    num_cars: int,
    num_persons: int,
    frame_count: int,
    total_frames: Optional[int] = None,
) -> np.ndarray:
    """
    Disegna overlay con statistiche sul frame.
    
    Args:
        frame: Frame da annotare
        stats_data: Dizionario con statistiche da StatisticsCollector
        num_cars: Numero di auto nel frame corrente
        num_persons: Numero di persone nel frame corrente
        frame_count: Numero frame corrente
        total_frames: Numero totale frame (opzionale, per progresso)
        
    Returns:
        Frame annotato
    """
    annotated = frame.copy()
    
    # Background semi-trasparente per overlay
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (300, 120), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, annotated, 0.4, 0, annotated)
    
    # Info overlay
    y_offset = 25
    cv2.putText(
        annotated,
        f"FPS: {stats_data['current_fps']:.1f}",
        (10, y_offset),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )
    y_offset += 25
    cv2.putText(
        annotated,
        f"Auto: {num_cars} | Persone: {num_persons}",
        (10, y_offset),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    y_offset += 25
    
    frame_info = f"Frame: {frame_count}"
    if total_frames:
        frame_info += f"/{total_frames}"
    cv2.putText(
        annotated,
        frame_info,
        (10, y_offset),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
    )
    y_offset += 20
    
    # Colore stato
    status = stats_data.get("status", "UNKNOWN")
    status_colors = {
        "RUNNING": (0, 255, 0),
        "PAUSED": (0, 165, 255),
        "STOPPED": (0, 0, 255),
        "ERROR": (0, 0, 255),
    }
    status_color = status_colors.get(status, (200, 200, 200))
    cv2.putText(
        annotated,
        f"Status: {status}",
        (10, y_offset),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        status_color,
        2,
    )
    
    return annotated


def _process_dashboard_commands(dashboard, paused: bool, stats, event_logger) -> Tuple[bool, bool]:
    """
    Processa comandi dal dashboard.
    
    Args:
        dashboard: Istanza DashboardWindow o None
        paused: Stato pausa attuale
        stats: StatisticsCollector
        event_logger: EventLogger
        
    Returns:
        Tuple (should_stop, new_paused_state)
    """
    if not dashboard:
        return False, paused
    
    command = dashboard.get_command()
    if command == "stop":
        return True, paused
    elif command == "pause":
        new_paused = not paused
        stats.set_status("PAUSED" if new_paused else "RUNNING")
        event_logger.log("video_paused" if new_paused else "video_resumed")
        return False, new_paused
    
    return False, paused


def _handle_screenshot_command(dashboard, frame: np.ndarray, frame_count: int, event_logger, stats) -> bool:
    """
    Gestisce comando screenshot dal dashboard.
    
    Args:
        dashboard: Istanza DashboardWindow o None
        frame: Frame da salvare
        frame_count: Numero frame corrente
        event_logger: EventLogger
        stats: StatisticsCollector
        
    Returns:
        True se screenshot salvato, False altrimenti
    """
    if not dashboard:
        return False
    
    try:
        if dashboard.command_queue.qsize() > 0:
            cmd = dashboard.command_queue.get_nowait()
            if cmd == "screenshot":
                screenshot_dir = Path("screenshot")
                screenshot_dir.mkdir(exist_ok=True)
                screenshot_path = screenshot_dir / f"frame_{frame_count:06d}.jpg"
                cv2.imwrite(str(screenshot_path), frame)
                event_logger.log("screenshot_taken", details=str(screenshot_path))
                stats.add_event("screenshot", f"Screenshot salvato: {screenshot_path.name}")
                return True
    except queue.Empty:
        pass
    
    return False


def _extract_detection_info(boxes, index: int) -> tuple[Optional[int], Optional[int], Optional[np.ndarray]]:
    """
    Estrae informazioni da una detection.
    
    Args:
        boxes: Oggetto boxes da risultato YOLO
        index: Indice della detection
        
    Returns:
        Tuple (class_id, track_id, bbox) oppure (None, None, None) se non valido
    """
    if boxes is None or len(boxes) <= index:
        return None, None, None
    
    cls = int(boxes.cls[index]) if hasattr(boxes, 'cls') else None
    track_id = int(boxes.id[index]) if hasattr(boxes, 'id') and boxes.id is not None else None
    bbox = boxes.xyxy[index].cpu().numpy() if hasattr(boxes, 'xyxy') else None
    
    return cls, track_id, bbox


def _draw_mask(frame: np.ndarray, mask: np.ndarray, color: Tuple[int, int, int], alpha: float = 0.15) -> None:
    """
    Disegna maschera di segmentazione sul frame con trasparenza.
    
    Args:
        frame: Frame su cui disegnare (modificato in-place)
        mask: Maschera binaria [H, W] o [H, W, 1]
        color: Colore BGR (es. (0, 255, 0) per verde)
        alpha: Trasparenza (0.0 = trasparente, 1.0 = opaco)
    """
    if mask is None or mask.size == 0:
        return
    
    # Assicura che mask sia 2D e booleana
    if len(mask.shape) == 3:
        mask = mask[:, :, 0] if mask.shape[2] == 1 else mask.max(axis=2)
    mask_binary = (mask > 0.5).astype(np.uint8) * 255
    
    if mask_binary.shape[:2] != frame.shape[:2]:
        mask_binary = cv2.resize(mask_binary, (frame.shape[1], frame.shape[0]))
    
    # Crea overlay colorato
    colored_mask = np.zeros_like(frame)
    colored_mask[mask_binary > 0] = color
    
    # Blend con frame originale
    blended = cv2.addWeighted(frame, 1 - alpha, colored_mask, alpha, 0)
    frame[:] = blended
    
    # Disegna contorno maschera
    contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) > 0:
        cv2.drawContours(frame, contours, -1, color, 2)


def _get_collision_type(event_type: str) -> str:
    """
    Converte tipo collisione da formato principale a formato test.
    
    Args:
        event_type: Tipo evento (es. "collision_auto_auto_major")
        
    Returns:
        Tipo semplificato ("both_moving" o "one_stopped")
    """
    if "major" in event_type:
        return "both_moving"
    elif "minor" in event_type or "base" in event_type:
        return "one_stopped"
    return "unknown"


def _video_progress_printer(stop_event: threading.Event) -> None:
    """
    Piccola interfaccia testuale: mentre il video viene elaborato,
    stampa uno spinner in console per indicare che il processo è attivo.
    """
    spinner = "|/-\\"
    idx = 0
    while not stop_event.is_set():
        print(f"\rElaborazione video in corso... {spinner[idx % len(spinner)]}", end="", flush=True)
        idx += 1
        time.sleep(0.2)
    # Pulizia riga
    print("\rElaborazione video completata.          ")


# ============================================================================
# SELEZIONE TELECAMERE - Pannello Interattivo
# ============================================================================

# File di configurazione permanente per le telecamere
CAMERAS_CONFIG_FILE = Path("config/cameras.json")


def save_cameras_config(cameras: List[Dict[str, str]], preserve_active_state: bool = False):
    """
    Salva la configurazione permanente delle telecamere in un file JSON.
    
    Args:
        cameras: Lista di dizionari con informazioni telecamere
        preserve_active_state: Se True, mantiene lo stato 'active' dalle telecamere esistenti
    """
    # Se preserva lo stato, carica config esistente e mantiene i flag active
    if preserve_active_state and CAMERAS_CONFIG_FILE.exists():
        try:
            with open(CAMERAS_CONFIG_FILE, "r", encoding="utf-8") as f:
                old_config = json.load(f)
            old_cameras = {cam.get("url"): cam.get("active", True) for cam in old_config.get("cameras", [])}
            
            # Applica stato active esistente alle nuove telecamere
            for cam in cameras:
                if cam.get("url") in old_cameras:
                    cam["active"] = old_cameras[cam["url"]]
                elif "active" not in cam:
                    cam["active"] = True  # Default per nuove telecamere
        except Exception:
            # Se errore, usa default
            for cam in cameras:
                if "active" not in cam:
                    cam["active"] = True
    else:
        # Assicura che tutte abbiano il campo active (default True)
        for cam in cameras:
            if "active" not in cam:
                cam["active"] = True
    
    config_data = {
        "nvr_info": {
            "ip": RTSP_IP,
            "port": RTSP_PORT,
            "user": RTSP_USER,
            "last_scan": datetime.now().isoformat()
        },
        "cameras": cameras
    }
    
    CAMERAS_CONFIG_FILE.parent.mkdir(exist_ok=True)
    with open(CAMERAS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)
    
    active_count = sum(1 for cam in cameras if cam.get("active", True))
    print(f"\nConfigurazione salvata: {active_count}/{len(cameras)} telecamere attive")


def update_cameras_active_state(cameras: List[Dict[str, str]]):
    """
    Aggiorna solo lo stato 'active' delle telecamere nella configurazione.
    
    Args:
        cameras: Lista telecamere con campo 'active' aggiornato
    """
    if not CAMERAS_CONFIG_FILE.exists():
        return
    
    try:
        with open(CAMERAS_CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        # Crea mapping URL -> active state
        active_map = {cam.get("url"): cam.get("active", True) for cam in cameras}
        
        # Aggiorna stato nelle telecamere esistenti
        for cam in config_data.get("cameras", []):
            if cam.get("url") in active_map:
                cam["active"] = active_map[cam["url"]]
        
        # Aggiorna timestamp
        config_data["nvr_info"]["last_update"] = datetime.now().isoformat()
        
        # Salva
        with open(CAMERAS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        active_count = sum(1 for cam in config_data.get("cameras", []) if cam.get("active", True))
        print(f"Configurazione aggiornata: {active_count}/{len(config_data.get('cameras', []))} telecamere attive")
    except Exception as e:
        print(f"Errore nell'aggiornamento configurazione: {e}")


def load_cameras_config() -> Optional[List[Dict[str, str]]]:
    """
    Carica la configurazione permanente delle telecamere dal file JSON.
    
    Returns:
        Lista telecamere configurate o None se file non esiste/invalido
    """
    if not CAMERAS_CONFIG_FILE.exists():
        return None
    
    try:
        with open(CAMERAS_CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        # Verifica che sia per lo stesso NVR
        nvr_info = config_data.get("nvr_info", {})
        if nvr_info.get("ip") != RTSP_IP or nvr_info.get("user") != RTSP_USER:
            print("Avviso: Configurazione trovata ma per un NVR diverso. Verifica necessaria.")
            return None
        
        cameras = config_data.get("cameras", [])
        if cameras:
            last_scan = nvr_info.get("last_scan", "sconosciuta")
            print(f"\nCaricate {len(cameras)} telecamere dalla configurazione")
            print(f"Ultima scansione: {last_scan}")
            return cameras
    except Exception as e:
        print(f"Errore nel caricamento configurazione: {e}")
        return None
    
    return None


def get_active_cameras(cameras: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Filtra solo le telecamere attive dalla lista.
    
    Args:
        cameras: Lista completa di telecamere
        
    Returns:
        Lista di telecamere con active=True
    """
    return [cam for cam in cameras if cam.get("active", True)]


def discover_cameras(max_channels: int = 16, timeout: float = 12.0, progress_callback=None) -> List[Dict[str, str]]:
    """
    Scopre automaticamente le telecamere disponibili sul NVR e salva foto anteprima.
    
    Args:
        max_channels: Numero massimo di canali da testare (default: 16)
        timeout: Timeout per ogni connessione in secondi (default: 12.0)
        progress_callback: Funzione callback per aggiornare il progresso (opzionale)
        
    Returns:
        Lista di dizionari con informazioni telecamere: [{"name": "...", "url": "...", "channel": ...}, ...]
    """
    discovered = []
    base_url = f"rtsp://{quote(RTSP_USER, safe='')}:{quote(RTSP_PASSWORD, safe='')}@{RTSP_IP}:{RTSP_PORT}"
    
    total_tests = max_channels * 2  # Main + Sub per ogni canale
    current_test = 0
    
    print(f"\nScansione telecamere in corso (fino a {max_channels} canali)...")
    print("Questo può richiedere qualche minuto...\n")
    
    if progress_callback:
        progress_callback(f"Inizializzazione scansione (testando {total_tests} stream)...")
    
    for channel in range(1, max_channels + 1):
        # Testa sia Main Stream che Sub Stream
        for stream_type, stream_num in [("Main", 1), ("Sub", 2)]:
            current_test += 1
            channel_num = channel * 100 + stream_num
            # Usa formato senza padding fisso per supportare canali >= 10 (es. 1302, 1602)
            url = f"{base_url}/Streaming/Channels/{channel_num}"
            
            status_msg = f"Testando Canale {channel} - {stream_type} Stream ({current_test}/{total_tests})..."
            print(f"Testando Canale {channel} - {stream_type} Stream ({channel_num})...", end=" ", flush=True)
            
            if progress_callback:
                progress_callback(status_msg)
            
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                # Per stream RTSP, attendi un po' prima di verificare se è aperto
                # La connessione potrebbe richiedere alcuni secondi
                time.sleep(1.0)  # Attesa iniziale per permettere la connessione
                if not cap.isOpened():
                    print("NO (stream non aperto dopo attesa)")
                    cap.release()
                    continue
            except Exception as e:
                print(f"NO (errore apertura: {e})")
                continue
            
            # Attesa iniziale per permettere alla telecamera di stabilizzarsi (2 secondi)
            time.sleep(2.0)
            
            # Prova a leggere più frame e scegli il migliore (non troppo scuro/grigio)
            start_time = time.time()
            ret = False
            best_frame = None
            best_score = 0  # Score combinato: luminosità + contrasto
            frame_count = 0
            max_frames_to_test = 30  # Testa fino a 30 frame per trovare il migliore
            
            while time.time() - start_time < timeout and frame_count < max_frames_to_test:
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    # Verifica che il frame sia valido
                    h, w = frame.shape[:2]
                    if h > 0 and w > 0:
                        # Converti a scala di grigi
                        if len(frame.shape) == 3:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        else:
                            gray = frame
                        
                        # Calcola luminosità media
                        brightness = np.mean(gray)
                        
                        # Calcola contrasto (deviazione standard)
                        contrast = np.std(gray)
                        
                        # Calcola score combinato (luminosità pesata + contrasto)
                        # Luminosità ottimale: 100-150, contrasto ottimale: >20
                        brightness_score = min(brightness / 150.0, 1.0) * 0.7  # Massimo a 150
                        contrast_score = min(contrast / 40.0, 1.0) * 0.3  # Massimo a 40
                        combined_score = brightness_score + contrast_score
                        
                        # Accetta solo frame con luminosità minima (evita frame troppo scuri)
                        # e contrasto minimo (evita frame grigi uniformi)
                        # Soglie ridotte per essere più permissivi durante la scansione
                        min_brightness = 20  # Ridotto da 40 per accettare anche frame più scuri
                        min_contrast = 5  # Ridotto da 10 per accettare anche frame con meno contrasto
                        
                        # Accetta qualsiasi frame valido (anche con score basso) per la scansione
                        # La scansione deve essere permissiva, la qualità verrà valutata dopo
                        if brightness >= min_brightness and contrast >= min_contrast:
                            # Scegli il frame con score migliore
                            if combined_score > best_score:
                                best_frame = frame.copy()
                                best_score = combined_score
                            
                            # Se il frame è ottimale (luminosità > 80 e contrasto > 20), accettalo subito
                            if brightness > 80 and contrast > 20:
                                break
                        elif brightness > 0:  # Accetta anche frame molto scuri se hanno almeno un po' di luminosità
                            # Frame molto scuro ma valido - accettalo comunque per la scansione
                            if best_frame is None:  # Solo se non abbiamo ancora trovato nulla
                                best_frame = frame.copy()
                                best_score = 0.1  # Score minimo
                        
                        frame_count += 1
                        time.sleep(0.2)  # Aspetta tra un frame e l'altro (aumentato)
                    else:
                        time.sleep(0.1)
                else:
                    time.sleep(0.1)
            
            # Verifica se lo stream era aperto prima di rilasciarlo
            was_opened = cap.isOpened() if cap is not None else False
            cap.release()
            
            # Usa il frame migliore trovato - per la scansione accettiamo anche frame con score basso
            # L'importante è verificare che lo stream esista, non la qualità perfetta
            if best_frame is not None:
                frame = best_frame
                ret = True
                # Debug: stampa info sul frame trovato
                if best_score < 0.3:
                    print(f" (score basso: {best_score:.2f}, ma accettato per scansione)")
            else:
                # Nessun frame valido trovato
                ret = False
                frame = None
                # Debug: verifica se il problema è la connessione
                if was_opened:
                    print("NO (stream aperto ma nessun frame valido)")
                else:
                    print("NO (stream non aperto)")
            
            if ret and frame is not None:
                name = f"Canale {channel} - {stream_type} Stream"
                camera_info = {
                    "name": name,
                    "url": url,
                    "channel": channel,
                    "stream_type": stream_type,
                    "channel_num": channel_num,
                    "active": True  # Di default tutte attive
                }
                discovered.append(camera_info)
                
                # Salva foto anteprima
                try:
                    preview_path = get_camera_preview_path(camera_info)
                    # Ridimensiona a 640x480 per anteprime più grandi e visibili
                    frame_resized = cv2.resize(frame, (640, 480))
                    cv2.imwrite(str(preview_path), frame_resized)
                    print("OK - TROVATA (foto salvata)")
                    
                    if progress_callback:
                        progress_callback(f"✓ Canale {channel} - {stream_type} trovato e salvato ({len(discovered)} trovate)")
                except Exception as e:
                    print(f"OK - TROVATA (errore salvataggio foto: {e})")
            else:
                print("NO")
    
    if progress_callback:
        progress_callback(f"Scansione completata! Trovate {len(discovered)} telecamere.")
    
    return discovered


class CameraConfigurationWindow:
    """Pannello per configurare quali telecamere sono attive."""
    
    def __init__(self, cameras: List[Dict[str, str]]):
        try:
            import tkinter as tk
            from tkinter import ttk
            self.tk = tk
            self.ttk = ttk
        except ImportError:
            print("Errore: Tkinter non disponibile per il pannello configurazione.")
            self.tk = None
            return
        
        self.cameras = cameras
        self.updated_cameras = None
        self.checkbox_vars = {}
        
        # Crea finestra
        self.root = self.tk.Tk()
        self.root.title("Configurazione Telecamere - Attiva/Disattiva")
        self.root.geometry("900x700")
        
        # Header
        header_frame = self.tk.Frame(self.root)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        title_label = self.tk.Label(
            header_frame,
            text=f"Configurazione Telecamere ({len(cameras)} totali)",
            font=("Arial", 16, "bold")
        )
        title_label.pack(side="left")
        
        # Contatore telecamere attive
        active_count = sum(1 for cam in cameras if cam.get("active", True))
        self.count_label = self.tk.Label(
            header_frame,
            text=f"{active_count} attive",
            font=("Arial", 12),
            fg="green"
        )
        self.count_label.pack(side="right", padx=10)
        
        # Frame con scrollbar
        canvas_frame = self.tk.Frame(self.root)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        scrollbar = self.tk.Scrollbar(canvas_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.canvas = self.tk.Canvas(
            canvas_frame,
            yscrollcommand=scrollbar.set,
            bg="#f0f0f0"
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.canvas.yview)
        
        # Frame interno
        self.inner_frame = self.tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        
        # Bind resize
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        self.inner_frame.bind('<Configure>', self._on_frame_configure)
        
        # Crea checkbox per ogni telecamera
        self._create_checkboxes()
        
        # Pulsanti controllo
        control_frame = self.tk.Frame(self.root)
        control_frame.pack(pady=10)
        
        select_all_btn = self.tk.Button(
            control_frame,
            text="Seleziona Tutte",
            command=self.select_all,
            font=("Arial", 10),
            width=15
        )
        select_all_btn.pack(side="left", padx=5)
        
        deselect_all_btn = self.tk.Button(
            control_frame,
            text="Deseleziona Tutte",
            command=self.deselect_all,
            font=("Arial", 10),
            width=15
        )
        deselect_all_btn.pack(side="left", padx=5)
        
        # Pulsanti finali
        button_frame = self.tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        save_button = self.tk.Button(
            button_frame,
            text="Salva Configurazione",
            command=self.save_config,
            font=("Arial", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            width=20,
            height=2
        )
        save_button.pack(side="left", padx=5)
        
        cancel_button = self.tk.Button(
            button_frame,
            text="Annulla",
            command=self.cancel,
            font=("Arial", 12),
            bg="#F44336",
            fg="white",
            width=15,
            height=2
        )
        cancel_button.pack(side="left", padx=5)
        
        # Info
        info_label = self.tk.Label(
            self.root,
            text="Seleziona le telecamere da monitorare. Solo quelle attive saranno disponibili per l'analisi.",
            font=("Arial", 9),
            fg="gray"
        )
        info_label.pack(pady=5)
    
    def _create_checkboxes(self):
        """Crea checkbox per ogni telecamera."""
        for i, cam in enumerate(self.cameras):
            # Frame per ogni telecamera
            cam_frame = self.tk.Frame(
                self.inner_frame,
                relief="raised",
                borderwidth=1,
                bg="white"
            )
            cam_frame.pack(fill="x", padx=5, pady=3)
            
            # Checkbox
            var = self.tk.BooleanVar(value=cam.get("active", True))
            self.checkbox_vars[cam["url"]] = var
            
            checkbox = self.tk.Checkbutton(
                cam_frame,
                variable=var,
                command=self.update_count,
                font=("Arial", 10, "bold")
            )
            checkbox.pack(side="left", padx=10, pady=5)
            
            # Nome telecamera
            name_label = self.tk.Label(
                cam_frame,
                text=cam["name"],
                font=("Arial", 10),
                bg="white"
            )
            name_label.pack(side="left", padx=5)
            
            # Dettagli
            details_text = f"Canale {cam['channel']} - {cam['stream_type']}"
            details_label = self.tk.Label(
                cam_frame,
                text=f"({details_text})",
                font=("Arial", 9),
                fg="gray",
                bg="white"
            )
            details_label.pack(side="left", padx=5)
            
            # URL (truncato)
            url_short = cam["url"].split("@")[-1] if "@" in cam["url"] else cam["url"]
            url_label = self.tk.Label(
                cam_frame,
                text=url_short,
                font=("Courier", 8),
                fg="darkgray",
                bg="white"
            )
            url_label.pack(side="left", padx=10)
    
    def _on_canvas_configure(self, event):
        """Gestisce resize del canvas."""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)
    
    def _on_frame_configure(self, event):
        """Gestisce resize del frame interno."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def select_all(self):
        """Seleziona tutte le telecamere."""
        for var in self.checkbox_vars.values():
            var.set(True)
        self.update_count()
    
    def deselect_all(self):
        """Deseleziona tutte le telecamere."""
        for var in self.checkbox_vars.values():
            var.set(False)
        self.update_count()
    
    def update_count(self):
        """Aggiorna contatore telecamere attive."""
        active_count = sum(1 for var in self.checkbox_vars.values() if var.get())
        self.count_label.config(text=f"{active_count} attive", fg="green" if active_count > 0 else "red")
    
    def save_config(self):
        """Salva la configurazione."""
        # Aggiorna stato active nelle telecamere
        updated_cameras = []
        for cam in self.cameras:
            cam_copy = cam.copy()
            cam_copy["active"] = self.checkbox_vars[cam["url"]].get()
            updated_cameras.append(cam_copy)
        
        self.updated_cameras = updated_cameras
        update_cameras_active_state(updated_cameras)
        self.root.quit()
        self.root.destroy()
    
    def cancel(self):
        """Annulla configurazione."""
        self.updated_cameras = None
        self.root.quit()
        self.root.destroy()
    
    def run(self) -> Optional[List[Dict[str, str]]]:
        """Avvia la finestra e restituisce le telecamere aggiornate."""
        if not self.tk:
            return None
        self.root.mainloop()
        return self.updated_cameras


def _get_camera_preview(url: str, timeout: float = 6.0) -> Optional[np.ndarray]:
    """
    Ottiene un frame di anteprima da una telecamera RTSP.
    
    Args:
        url: URL RTSP della telecamera
        timeout: Timeout in secondi (default: 6.0)
        
    Returns:
        Frame BGR come numpy array o None se fallisce
    """
    cap = None
    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return None
        
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FPS, 5)  # Limita FPS per velocizzare
        
        start_time = time.time()
        ret, frame = False, None
        
        # Prova a leggere più frame (a volte i primi sono vuoti)
        attempts = 0
        max_attempts = 10
        
        while time.time() - start_time < timeout and attempts < max_attempts:
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                # Verifica che il frame sia valido
                h, w = frame.shape[:2]
                if h > 0 and w > 0:
                    break
            time.sleep(0.15)
            attempts += 1
        
        if cap:
            cap.release()
        
        return frame if (ret and frame is not None and frame.size > 0) else None
    except Exception:  # noqa: BLE001
        if cap:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        return None


def get_camera_preview_path(camera: dict) -> Path:
    """
    Restituisce il path della foto anteprima per una telecamera.
    
    Args:
        camera: Dizionario con informazioni telecamera (deve contenere 'channel' e 'stream_type')
        
    Returns:
        Path completo del file immagine anteprima
    """
    channel = camera.get("channel", "unknown")
    stream_type = camera.get("stream_type", "unknown").lower()
    filename = f"cam_{channel}_{stream_type}.jpg"
    return CAMERA_PREVIEWS_DIR / filename


class ScanProgressWindow:
    """Finestra di progresso durante la scansione telecamere."""
    
    def __init__(self, parent_root):
        try:
            import tkinter as tk
            self.tk = tk
        except ImportError:
            self.tk = None
            return
        
        self.root = parent_root
        self.window = self.tk.Toplevel(self.root)
        self.window.title("Scansione in corso...")
        self.window.geometry("500x200")
        self.window.transient(self.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)  # Disabilita chiusura X
        
        # Label principale
        self.status_label = self.tk.Label(
            self.window,
            text="Scansione telecamere in corso...",
            font=("Arial", 14, "bold"),
            pady=20
        )
        self.status_label.pack()
        
        # Progress bar (testuale)
        self.progress_var = self.tk.StringVar(value="Inizializzazione...")
        self.progress_label = self.tk.Label(
            self.window,
            textvariable=self.progress_var,
            font=("Arial", 10),
            pady=10,
            wraplength=450,
            justify="center"
        )
        self.progress_label.pack()
        
        # Bottone annulla
        self.cancel_button = self.tk.Button(
            self.window,
            text="Annulla",
            command=self.cancel,
            bg="#F44336",
            fg="white",
            font=("Arial", 10),
            width=15
        )
        self.cancel_button.pack(pady=10)
        
        self.cancelled = False
    
    def update_status(self, message: str):
        """Aggiorna il messaggio di stato."""
        if not self.cancelled and self.tk:
            try:
                self.progress_var.set(message)
                self.window.update_idletasks()
            except Exception:  # noqa: BLE001
                pass  # Finestra chiusa
    
    def cancel(self):
        """Annulla la scansione."""
        self.cancelled = True
        if self.tk:
            try:
                self.window.destroy()
            except Exception:  # noqa: BLE001
                pass
    
    def close(self):
        """Chiudi la finestra."""
        if self.tk and not self.cancelled:
            try:
                self.window.destroy()
            except Exception:  # noqa: BLE001
                pass


class CameraSelectionWindow:
    """Finestra migliorata per selezionare una telecamera con anteprime."""
    
    def __init__(self, cameras: List[Dict[str, str]], on_refresh_callback=None, on_config_callback=None, show_only_active: bool = True):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            print("Errore: Tkinter non disponibile. Installalo con il tuo sistema operativo.")
            self.tk = None
            self.pillow_available = False
            self.PIL = None
            self.ImageTk = None
            return
        
        self.tk = tk
        self.ttk = ttk
        
        # Verifica Pillow separatamente per dare messaggio più chiaro
        try:
            from PIL import Image, ImageTk
            self.PIL = Image
            self.ImageTk = ImageTk
            self.pillow_available = True
        except ImportError:
            print("\n" + "="*60)
            print("ATTENZIONE: Pillow non installato")
            print("="*60)
            print("Le anteprime non verranno visualizzate.")
            print("Per installare Pillow, esegui:")
            print("  pip install Pillow")
            print("="*60 + "\n")
            self.PIL = None
            self.ImageTk = None
            self.pillow_available = False
        
        # Filtra solo telecamere attive se richiesto
        if show_only_active:
            self.cameras = get_active_cameras(cameras)
            self.all_cameras = cameras  # Mantieni tutte per configurazione
        else:
            self.cameras = cameras
            self.all_cameras = cameras
        
        self.selected_url = None
        self.on_refresh = on_refresh_callback
        self.on_config = on_config_callback
        self.preview_threads = {}
        self.running = True
        
        # Crea finestra - Dimensione aumentata per anteprime più grandi
        self.root = self.tk.Tk()
        self.root.title("Selezione Telecamera")
        self.root.geometry("1600x1100")  # Aumentato per ospitare anteprime 640x480
        
        # Header con pulsanti
        header_frame = self.tk.Frame(self.root)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        active_count = len(self.cameras)
        total_count = len(self.all_cameras)
        title_text = f"Telecamere Attive ({active_count}/{total_count})" if show_only_active else f"Telecamere ({total_count})"
        
        title_label = self.tk.Label(
            header_frame,
            text=title_text,
            font=("Arial", 16, "bold")
        )
        title_label.pack(side="left")
        
        # Pulsanti a destra
        buttons_frame = self.tk.Frame(header_frame)
        buttons_frame.pack(side="right")
        
        if self.on_config:
            config_button = self.tk.Button(
                buttons_frame,
                text="Configura Telecamere",
                command=self.open_config,
                font=("Arial", 11),
                bg="#FF9800",
                fg="white",
                width=20,
                height=1
            )
            config_button.pack(side="left", padx=5)
        
        if self.on_refresh:
            refresh_button = self.tk.Button(
                buttons_frame,
                text="Verifica Telecamere",
                command=self.refresh_cameras,
                font=("Arial", 11),
                bg="#2196F3",
                fg="white",
                width=18,
                height=1
            )
            refresh_button.pack(side="left", padx=5)
        
        # Canvas con scrollbar per la griglia
        canvas_frame = self.tk.Frame(self.root)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        scrollbar = self.tk.Scrollbar(canvas_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.canvas = self.tk.Canvas(
            canvas_frame,
            yscrollcommand=scrollbar.set,
            bg="#f0f0f0"
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.canvas.yview)
        
        # Frame interno per contenere la griglia
        self.inner_frame = self.tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        
        # Bind resize
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        self.inner_frame.bind('<Configure>', self._on_frame_configure)
        
        # Griglia telecamere
        self.camera_widgets = []
        self._create_camera_grid()
        
        # Pulsanti finali
        button_frame = self.tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        cancel_button = self.tk.Button(
            button_frame,
            text="Annulla",
            command=self.cancel,
            font=("Arial", 12),
            bg="#F44336",
            fg="white",
            width=15,
            height=2
        )
        cancel_button.pack(side="left", padx=5)
        
        # Info
        info_label = self.tk.Label(
            self.root,
            text="Click per selezionare • Doppio click per anteprima grande",
            font=("Arial", 9),
            fg="gray"
        )
        info_label.pack(pady=5)
        
        # Avvia caricamento anteprime in background
        self._start_preview_loading()
    
    def _create_camera_grid(self):
        """Crea la griglia di telecamere con anteprime."""
        cols = 2  # Ridotto a 2 colonne per molto più spazio e anteprime più grandi
        preview_size = (640, 480)  # Aumentato a 640x480 per anteprime ancora più grandi e visibili
        
        for i, cam in enumerate(self.cameras):
            row = i // cols
            col = i % cols
            
            # Frame per ogni telecamera - Bordo più evidente per migliore separazione
            cam_frame = self.tk.Frame(
                self.inner_frame,
                relief="raised",
                borderwidth=3,  # Aumentato da 2 a 3 per bordo più evidente
                bg="white",
                highlightbackground="#cccccc",
                highlightthickness=1
            )
            cam_frame.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")  # Padding aumentato
            
            # Label per anteprima (placeholder)
            preview_text = "Caricamento anteprima..." if self.pillow_available else "Anteprima non disponibile"
            preview_label = self.tk.Label(
                cam_frame,
                text=preview_text,
                bg="#e0e0e0",
                width=80,  # Aumentato per ospitare immagini 640x480
                height=30,  # Aumentato per ospitare immagini 640x480
                font=("Arial", 10),
                justify="center",
                cursor="hand2"  # Cursore mano per indicare clickabilità
            )
            preview_label.pack(pady=5)
            
            # Nome telecamera - Font più grande per migliore leggibilità
            name_label = self.tk.Label(
                cam_frame,
                text=cam["name"],
                font=("Arial", 14, "bold"),  # Aumentato da 10 a 14
                bg="white",
                fg="#1a1a1a"  # Colore più scuro per maggiore contrasto
            )
            name_label.pack(pady=(5, 2))
            
            # Dettagli - Font più grande per migliore leggibilità
            details_text = f"Canale {cam['channel']} - {cam['stream_type']}"
            details_label = self.tk.Label(
                cam_frame,
                text=details_text,
                font=("Arial", 11),  # Aumentato da 8 a 11
                fg="#555555",  # Grigio più scuro per migliore visibilità
                bg="white"
            )
            details_label.pack(pady=(0, 5))
            
            # Bind click per selezione (click singolo = seleziona, doppio click = anteprima grande)
            for widget in [preview_label, name_label, details_label, cam_frame]:
                widget.bind("<Button-1>", lambda e, url=cam["url"]: self.select_camera_by_url(url))
                # Doppio click sull'anteprima per vedere immagine grande
                if widget == preview_label:
                    widget.bind("<Double-Button-1>", lambda e, c=cam: self._show_large_preview(c))
            
            self.camera_widgets.append({
                "frame": cam_frame,
                "preview": preview_label,
                "name": name_label,
                "details": details_label,
                "camera": cam
            })
    
    def _start_preview_loading(self):
        """Avvia il caricamento delle anteprime in background."""
        if not self.pillow_available:
            # Se Pillow non è disponibile, mostra solo testo
            for widget in self.camera_widgets:
                widget["preview"].config(
                    text="Anteprima non disponibile\n(Pillow non installato)",
                    bg="#ffffcc",
                    font=("Arial", 8),
                    justify="center"
                )
            return
        
        # Carica anteprime solo se Pillow è disponibile
        # Aggiungi delay per evitare sovraccarico (carica una ogni 200ms)
        def load_with_delay(widget, delay):
            def delayed_load():
                time.sleep(delay)
                if self.running:
                    self._load_preview_thread(widget)
            threading.Thread(target=delayed_load, daemon=True).start()
        
        for idx, widget in enumerate(self.camera_widgets):
            load_with_delay(widget, idx * 0.2)  # 200ms tra ogni caricamento
    
    def _load_preview_thread(self, widget):
        """Carica anteprima statica da file salvato durante la scansione."""
        def load_preview():
            try:
                cam = widget["camera"]
                preview_path = get_camera_preview_path(cam)
                
                if preview_path.exists() and self.running:
                    try:
                        # Carica foto statica salvata
                        pil_image = self.PIL.open(preview_path)
                        
                        # Aggiorna UI nel thread principale
                        if self.running:
                            self.root.after(0, lambda w=widget, img=pil_image: self._update_preview_from_pil(w, img))
                    except Exception as e:
                        # Errore nel caricamento foto
                        if self.running:
                            try:
                                self.root.after(0, lambda w=widget, msg="Errore caricamento": self._update_preview_error(w, msg))
                            except RuntimeError:
                                pass  # Finestra già chiusa, ignora
                else:
                    # Nessuna foto disponibile - mostra placeholder
                    if self.running:
                        try:
                            self.root.after(0, lambda w=widget: self._update_preview_error(w, "Nessuna anteprima"))
                        except RuntimeError:
                            pass  # Finestra già chiusa, ignora
            except Exception as e:
                # Errore generale
                if self.running:
                    try:
                        self.root.after(0, lambda w=widget, msg="Errore": self._update_preview_error(w, msg))
                    except RuntimeError:
                        pass  # Finestra già chiusa, ignora
        
        thread = threading.Thread(target=load_preview, daemon=True)
        thread.start()
    
    def _update_preview_from_pil(self, widget, pil_image):
        """Crea PhotoImage da PIL Image e aggiorna l'anteprima (chiamato nel thread principale)."""
        if not self.running:
            return
        try:
            # Crea PhotoImage nel thread principale (requisito Tkinter)
            photo = self.ImageTk.PhotoImage(image=pil_image)
            widget["preview"].config(image=photo, text="")
            widget["preview"].image = photo  # Mantieni riferimento
        except Exception:  # noqa: BLE001
            pass  # Ignora errori di UI (finestra chiusa, ecc.)
    
    def _update_preview_error(self, widget, error_msg: str):
        """Aggiorna l'anteprima con messaggio di errore."""
        if not self.running:
            return
        try:
            widget["preview"].config(
                image="",
                text=error_msg,
                bg="#ffcccc",
                fg="red",
                font=("Arial", 8)
            )
        except (RuntimeError, AttributeError):  # Finestra chiusa o widget distrutto
            pass
        except Exception:  # noqa: BLE001
            pass
    
    def _show_large_preview(self, camera: dict):
        """Mostra un'anteprima grande della telecamera in una finestra separata."""
        if not self.pillow_available:
            return
        
        # Crea finestra popup
        popup = self.tk.Toplevel(self.root)
        popup.title(f"Anteprima: {camera['name']}")
        popup.geometry("800x600")
        popup.transient(self.root)
        popup.grab_set()  # Blocca interazione con finestra principale
        
        # Frame principale per immagine
        image_frame = self.tk.Frame(popup, bg="white")
        image_frame.pack(expand=True, fill="both", padx=10, pady=10)
        
        # Label per caricamento
        loading_label = self.tk.Label(
            image_frame,
            text="Caricamento anteprima grande...",
            font=("Arial", 12),
            bg="white"
        )
        loading_label.pack(expand=True, fill="both")
        
        # Frame per bottone in fondo
        button_frame = self.tk.Frame(popup)
        button_frame.pack(pady=10)
        
        # Bottone chiudi
        close_button = self.tk.Button(
            button_frame,
            text="Chiudi",
            command=popup.destroy,
            font=("Arial", 10),
            bg="#F44336",
            fg="white",
            width=15
        )
        close_button.pack()
        
        def load_large_preview():
            """Carica anteprima grande in thread separato."""
            try:
                frame = _get_camera_preview(camera["url"], timeout=8.0)
                if frame is not None:
                    # Ridimensiona mantenendo aspect ratio, max 800x600
                    h, w = frame.shape[:2]
                    max_w, max_h = 780, 540  # Lascia spazio per padding
                    scale = min(max_w / w, max_h / h, 1.0)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    
                    frame_resized = cv2.resize(frame, (new_w, new_h))
                    frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                    pil_image = self.PIL.fromarray(frame_rgb)
                    photo = self.ImageTk.PhotoImage(image=pil_image)
                    
                    # Aggiorna UI
                    def update_ui():
                        loading_label.config(image=photo, text="")
                        loading_label.image = photo  # Mantieni riferimento
                    
                    popup.after(0, update_ui)
                else:
                    popup.after(0, lambda: loading_label.config(
                        text="Errore nel caricamento anteprima\n\nProva a fare doppio click di nuovo",
                        fg="red",
                        font=("Arial", 10)
                    ))
            except Exception as e:
                popup.after(0, lambda: loading_label.config(
                    text=f"Errore: {str(e)[:50]}\n\nProva a fare doppio click di nuovo",
                    fg="red",
                    font=("Arial", 10)
                ))
        
        # Avvia caricamento
        threading.Thread(target=load_large_preview, daemon=True).start()
    
    def _on_canvas_configure(self, event):
        """Gestisce resize del canvas."""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)
    
    def _on_frame_configure(self, event):
        """Gestisce resize del frame interno."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def select_camera_by_url(self, url: str):
        """Seleziona telecamera per URL."""
        self.selected_url = url
        selected_cam = next((c for c in self.cameras if c["url"] == url), None)
        if selected_cam:
            cam_name = selected_cam["name"]
            print(f"\nTelecamera selezionata: {cam_name}")
            print(f"URL: {url}")
        self.root.quit()
        self.root.destroy()
    
    def open_config(self):
        """Apre pannello configurazione telecamere."""
        if self.on_config:
            self.running = False
            self.root.quit()
            self.selected_url = "CONFIG"  # Segnale speciale
            self.root.destroy()
    
    def refresh_cameras(self):
        """Avvia nuova scansione telecamere."""
        if self.on_refresh:
            self.running = False
            self.root.quit()
            self.selected_url = "REFRESH"  # Segnale speciale
            self.root.destroy()
    
    def cancel(self):
        """Annulla selezione."""
        self.running = False
        self.selected_url = None
        self.root.quit()
        self.root.destroy()
    
    def run(self) -> Optional[str]:
        """Avvia la finestra e restituisce l'URL selezionato."""
        if not self.tk:
            return None
        self.root.mainloop()
        return self.selected_url


def select_camera_interactive() -> Optional[str]:
    """
    Mostra un pannello interattivo per selezionare una telecamera.
    Usa configurazione permanente se disponibile, altrimenti fa nuova scansione.
    Mostra solo telecamere attive per l'analisi.
    
    Returns:
        URL RTSP della telecamera selezionata o None se annullato
    """
    def do_refresh():
        """Callback per refresh telecamere."""
        return True
    
    def do_config():
        """Callback per configurazione telecamere."""
        return True
    
    while True:
        # Prova a caricare configurazione esistente
        all_cameras = load_cameras_config()
        
        if not all_cameras:
            # Prima volta: scansione completa
            print("\n" + "="*60)
            print("PRIMA CONFIGURAZIONE - SCOPERTA TELECAMERE")
            print("="*60)
            print("Scansione iniziale in corso...")
            
            all_cameras = discover_cameras(max_channels=16, timeout=12.0)
            
            if not all_cameras:
                print("\nNessuna telecamera trovata. Verifica:")
                print(f"  - IP NVR: {RTSP_IP}")
                print(f"  - Credenziali: {RTSP_USER}")
                print("  - Connessione di rete")
                return None
            
            # Salva configurazione (tutte attive di default)
            save_cameras_config(all_cameras)
            print(f"\n{len(all_cameras)} telecamera(e) configurate e salvate!")
            print("Tutte le telecamere sono attive di default.")
            print("Usa 'Configura Telecamere' per selezionare solo quelle da monitorare.\n")
        
        # Filtra solo telecamere attive per la selezione
        active_cameras = get_active_cameras(all_cameras)
        active_count = len(active_cameras)
        total_count = len(all_cameras)
        
        if active_count == 0:
            print(f"\nNessuna telecamera attiva! Configura le telecamere prima di procedere.")
            # Apri direttamente configurazione
            config_window = CameraConfigurationWindow(all_cameras)
            updated = config_window.run()
            if updated:
                all_cameras = updated
                active_cameras = get_active_cameras(all_cameras)
                if len(active_cameras) == 0:
                    print("Nessuna telecamera attivata. Uscita.")
                    return None
                continue
            else:
                return None
        
        print(f"\nCaricamento pannello: {active_count} telecamera(e) attiva(e) su {total_count} totali...\n")
        
        # Mostra pannello selezione con anteprime (solo attive)
        selection_window = CameraSelectionWindow(
            all_cameras,
            on_refresh_callback=do_refresh,
            on_config_callback=do_config,
            show_only_active=True
        )
        selected_url = selection_window.run()
        
        # Gestisci configurazione
        if selected_url == "CONFIG":
            print("\nApertura pannello configurazione telecamere...\n")
            config_window = CameraConfigurationWindow(all_cameras)
            updated = config_window.run()
            if updated:
                all_cameras = updated
                # Ricarica per mostrare solo attive
                continue
            else:
                # Se annullato, continua con le telecamere attuali
                continue
        
        # Gestisci refresh
        if selected_url == "REFRESH":
            print("\n" + "="*60)
            print("VERIFICA TELECAMERE - NUOVA SCANSIONE")
            print("="*60)
            
            # Crea finestra temporanea per progresso
            try:
                import tkinter as tk
                temp_root = tk.Tk()
                temp_root.withdraw()  # Nascondi finestra principale temporanea
                progress_window = ScanProgressWindow(temp_root)
            except Exception:  # noqa: BLE001
                progress_window = None
            
            # Variabili per il risultato della scansione
            scan_result = {"cameras": None, "error": None, "done": False}
            
            # Funzione per scansione in thread
            def do_scan():
                try:
                    scan_result["cameras"] = discover_cameras(
                        max_channels=16,
                        timeout=12.0,  # Corretto da 2.0 a 12.0 per permettere più frame testati
                        progress_callback=progress_window.update_status if progress_window else None
                    )
                except Exception as e:
                    scan_result["error"] = str(e)
                finally:
                    scan_result["done"] = True
                    if progress_window:
                        progress_window.close()
                    try:
                        temp_root.quit()
                    except Exception:  # noqa: BLE001
                        pass
            
            # Avvia scansione in thread separato
            scan_thread = threading.Thread(target=do_scan, daemon=True)
            scan_thread.start()
            
            # Aggiorna finestra di progresso mentre lavora
            if progress_window:
                try:
                    # Timeout per il mainloop
                    temp_root.after(300000, temp_root.quit)  # 5 minuti max
                    temp_root.mainloop()
                except Exception:  # noqa: BLE001
                    pass
            
            # Aspetta che finisca la scansione (max 10 minuti)
            scan_thread.join(timeout=600)
            
            # Chiudi finestra temporanea
            try:
                temp_root.destroy()
            except Exception:  # noqa: BLE001
                pass
            
            new_cameras = scan_result["cameras"]
            
            if new_cameras:
                # Preserva stato active esistente
                save_cameras_config(new_cameras, preserve_active_state=True)
                all_cameras = load_cameras_config()
                print(f"\n{len(all_cameras)} telecamera(e) verificate e configurate!")
                continue  # Riprova a mostrare il pannello
            else:
                if scan_result["error"]:
                    print(f"\nErrore durante la scansione: {scan_result['error']}")
                else:
                    print("\nNessuna telecamera trovata durante la verifica.")
                return None
        
        if selected_url:
            # Trova nome telecamera selezionata
            selected_cam = next((c for c in all_cameras if c["url"] == selected_url), None)
            if selected_cam:
                cam_name = selected_cam["name"]
                stream_type = selected_cam.get("stream_type", "")
                print(f"\nTelecamera selezionata: {cam_name}")
                print(f"URL: {selected_url}")
                
                # Avviso se è Sub Stream (risoluzione più bassa)
                if stream_type == "Sub":
                    print(f"\n{'!'*60}")
                    print("ATTENZIONE: Hai selezionato SUB STREAM (risoluzione bassa)")
                    print(f"{'!'*60}")
                    print("Per migliore accuratezza, usa MAIN STREAM che ha risoluzione più alta.")
                    print("Sub Stream tipicamente: 640x480 o 800x600")
                    print("Main Stream tipicamente: 1920x1080 o superiore")
                    print(f"{'!'*60}\n")
            return selected_url
        else:
            print("\nSelezione annullata.")
            return None


def analyze_video(
    video_path,  # Può essere Path o str (per URL RTSP)
    model_name: str = "yolo11n.pt",
    enable_yolo: bool = False,  # NUOVO: carica YOLO solo se True (default False per performance)
    enable_person_detection: bool = True,  # Rilevamento persone (classe 0)
    enable_vehicle_detection: bool = False,  # Rilevamento veicoli (classi 2,3,5,7: car, motorcycle, bus, truck)
    enable_plates: bool = False,
    enable_dashboard: bool = True,
    log_file = None,  # Optional[Path] - rimosso type hint per evitare conflitto con Path importato
    enable_collision: bool = False,
    enable_person_safety: bool = False,  # DEFAULT: False (modulo opzionale)
    enable_person_loitering: bool = False,  # DEFAULT: False
    enable_person_fall: bool = False,  # DEFAULT: False
    enable_person_vehicle_interaction: bool = False,  # DEFAULT: False - monitora persone intorno a veicoli
    enable_person_wall_writing: bool = False,  # DEFAULT: False - monitora scrittura su muro
    imgsz: int = 640,  # Risoluzione YOLO (più bassa = più veloce)
    frame_callback: Optional[Callable[[np.ndarray], None]] = None,  # Callback per frame (per pannello)
    stop_flag: Optional[Callable[[], bool]] = None,  # Funzione per controllare se fermare
    stats_collector: Optional[Any] = None,  # StatisticsCollector condiviso (opzionale)
    get_params_callback: Optional[Callable[[], Dict]] = None,  # Callback per ottenere parametri aggiornati in real-time
) -> bool:
    """
    Esegue il tracking YOLO (con ByteTrack integrato Ultralytics) su un video MP4.
    - Usa moduli opzionali per funzionalità avanzate (YOLO, OCR, Collision, Person Safety)
    - Se enable_yolo=False, modalità solo visualizzazione (nessun YOLO)
    - Legge le targhe delle auto usando EasyOCR (solo se enable_plates=True)
    - Salva un video annotato in 'runs/track/...' con targhe visualizzate.
    """
    # Import moduli core
    from modules.core.statistics import StatisticsCollector
    from modules.core.event_logger import EventLogger
    
    # Verifica se è un file o un URL RTSP
    # Gestisce sia Path che stringhe (per URL RTSP)
    # NOTA: Path è già importato all'inizio del file, non serve importarlo di nuovo
    
    if isinstance(video_path, Path):
        video_path_str = str(video_path)
    else:
        video_path_str = video_path  # Già una stringa (URL RTSP)
    
    is_rtsp = video_path_str.startswith("rtsp://")
    
    # Per URL RTSP, non verificare se è un file
    if not is_rtsp:
        # Per file locali, verifica che esista
        video_path_obj = Path(video_path_str) if isinstance(video_path, str) else video_path
        if not video_path_obj.is_file():
            error_msg = f"Errore: video non trovato -> {video_path_obj.resolve()}"
            print(error_msg)
            if stats_collector:
                stats_collector.add_log(error_msg)
            return False

    # Determina se serve YOLO (almeno una funzionalità lo richiede)
    needs_yolo = enable_yolo or enable_plates or enable_collision or enable_person_safety
    
    # Carica YOLO solo se necessario
    model = None
    if needs_yolo:
        from modules.detection.yolo_module import YOLOModule
        
        print(f"[DEBUG] Caricamento modello YOLO: {model_name}")
        if stats_collector:
            stats_collector.add_log(f"⏳ Caricamento modello YOLO: {model_name}... (può richiedere alcuni secondi)")
            stats_collector.set_status("LOADING_MODEL")
        
        start_time = time.time()
        model = YOLOModule.get_model(model_name)
        load_time = time.time() - start_time
        
        if model is None:
            error_msg = f"Errore: impossibile caricare il modello YOLO '{model_name}'"
            print(error_msg)
            if stats_collector:
                stats_collector.add_log(error_msg)
                stats_collector.set_status("ERROR")
            return False
        
        print(f"[DEBUG] analyze_video: Modello YOLO caricato in {load_time:.2f} secondi")
        if stats_collector:
            stats_collector.add_log(f"✅ Modello caricato in {load_time:.2f} secondi")
            stats_collector.set_status("RUNNING")
    else:
        print(f"[DEBUG] analyze_video: Modalità solo visualizzazione - YOLO NON caricato (enable_yolo={enable_yolo}, plates={enable_plates}, collision={enable_collision}, person={enable_person_safety})")

    # Configura lettura targhe (richiede YOLO)
    plate_manager = None
    if enable_plates:
        if not model:
            print("⚠️  Lettura targhe richiede YOLO. Abilita 'enable_yolo' o 'enable_plates' richiede YOLO automaticamente.")
        else:
            from modules.features.ocr_module import OCRModule, LicensePlateManager
            ocr_reader = OCRModule.get_reader()
            if ocr_reader is not None:
                plate_manager = LicensePlateManager(ocr_reader)
                print("Lettura targhe: ABILITATA (EasyOCR)")
            else:
                print("Lettura targhe: DISABILITATA (EasyOCR non disponibile)")
    else:
        print("Lettura targhe: DISABILITATA (configurazione)")

    # Inizializza log CSV per collisioni
    collision_log = [] if enable_collision else None
    logged_collision_pairs = {}  # {(id1, id2): last_frame} per evitare duplicati
    
    # Area di esclusione (opzionale, può essere configurata in futuro)
    exclusion_zone = None  # (x1, y1, x2, y2) area da escludere

    video_name = (Path(video_path_str).name if not is_rtsp else f"RTSP Stream ({video_path_str.split('@')[0]}@***)")
    print(f"[DEBUG] analyze_video: Avvio analisi {'stream RTSP' if is_rtsp else 'video'} con tracking su: {video_name}")
    print(f"[DEBUG] analyze_video: is_rtsp={is_rtsp}, video_path={video_path_str[:50]}...")

    # Apri video con OpenCV (supporta sia file che URL RTSP)
    video_source = video_path_str  # Usa sempre la stringa (funziona sia per file che per URL)
    print(f"[DEBUG] analyze_video: Tentativo apertura {'stream RTSP' if is_rtsp else 'video'}: {video_source.split('@')[0] if is_rtsp else video_source}@***")
    
    if is_rtsp:
        # Per RTSP, usa CAP_FFMPEG e imposta buffer size piccolo per ridurre latenza
        cap = cv2.VideoCapture(video_source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print(f"[DEBUG] analyze_video: VideoCapture creato per RTSP, isOpened()={cap.isOpened()}")
    else:
        cap = cv2.VideoCapture(video_source)
        print(f"[DEBUG] analyze_video: VideoCapture creato per file, isOpened()={cap.isOpened()}")
    
    if not cap.isOpened():
        error_source = video_source.split('@')[0] + "@***" if is_rtsp else str(video_path.resolve())
        if is_rtsp:
            error_msg = f"[DEBUG] analyze_video: ERRORE - impossibile aprire lo stream RTSP -> {error_source}\nVerifica che:\n- La connessione di rete sia attiva e l'URL RTSP sia corretto\n- Le credenziali RTSP siano corrette\n- La telecamera sia raggiungibile"
        else:
            error_msg = f"[DEBUG] analyze_video: ERRORE - impossibile aprire il video -> {error_source}\nVerifica che:\n- Il file esista\n- Il formato video sia supportato (MP4, AVI, MOV, etc.)\n- Il file non sia corrotto"
        print(error_msg)
        if stats_collector:
            stats_collector.add_log(error_msg)
        print(f"[DEBUG] analyze_video: RETURN False (cap non aperto)")
        return False
    
    # Debug: verifica apertura video
    print(f"[DEBUG] {'Stream RTSP' if is_rtsp else 'Video'} aperto: {video_source.split('@')[0] if is_rtsp else video_path}")
    
    # Per stream RTSP, verifica che lo stream sia effettivamente disponibile
    if is_rtsp:
        print(f"[DEBUG] Verifica disponibilità frame RTSP...")
        # Prova a leggere un frame per verificare che lo stream funzioni
        test_ret, test_frame = cap.read()
        if not test_ret or test_frame is None:
            print(f"[WARNING] Primo tentativo di lettura frame RTSP fallito, continuo comunque (potrebbe richiedere più tempo)")
        else:
            print(f"[DEBUG] Primo frame RTSP ricevuto con successo: {test_frame.shape}")
            # Rileggi il frame (il primo potrebbe essere vuoto)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset alla posizione iniziale
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_rtsp else 0
    print(f"[DEBUG] {'Stream' if is_rtsp else 'Video'} info: FPS={fps}, Frame totali={'N/A (streaming)' if is_rtsp else frame_count_total}")
    if stats_collector:
        stats_collector.add_log(f"{'Stream RTSP' if is_rtsp else 'Video'} aperto: FPS={fps}, Frame totali={'N/A (streaming)' if is_rtsp else frame_count_total}")

    # NOTA: Per file video NON usiamo FrameBuffer - leggiamo direttamente con cap.read()
    # Il FrameBuffer è utile solo per streaming live (RTSP/webcam) dove vogliamo separare lettura/elaborazione
    # Per file video, la lettura diretta è più semplice e affidabile

    # Ottieni proprietà del video/stream
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_rtsp else 0  # Per RTSP non abbiamo frame totali

    # Prepara video di output
    output_dir = Path("runs") / "track"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "video_with_plates.mp4"
    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    # Inizializza dashboard e logging (usa moduli core)
    stats = stats_collector if stats_collector is not None else StatisticsCollector()
    stats.set_status("RUNNING")
    
    event_logger = None
    if log_file is None:
        log_file = Path("logs") / f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    event_logger = EventLogger(log_file)
    event_logger.log("video_started", details=f"{'Stream RTSP' if is_rtsp else 'Video'}: {video_name}")

    # Collision detector (solo veicoli, richiede YOLO)
    collision_detector = None
    if enable_collision:
        if not model:
            print("⚠️  Rilevamento collisioni richiede YOLO. Abilita 'enable_yolo'.")
        else:
            from modules.features.collision_module import CollisionModule
            # Path già importato all'inizio del file
            
            def _on_collision_event(ev: Dict) -> None:
                print(f"[CALLBACK] _on_collision_event CHIAMATO! type={ev.get('type')}, vehicle_ids={ev.get('vehicle_ids')}")
                details = ev.get("details", {})
                msg_parts = [f"Collisione tra auto {ev['vehicle_ids']}"]
                if details.get("approach_rate") is not None:
                    msg_parts.append(f"avvicinamento: {details['approach_rate']*100:.1f}%")
                if details.get("vehicle1_started_moving") or details.get("vehicle2_started_moving"):
                    msg_parts.append("(veicolo fermo ha iniziato a muoversi)")
                if details.get("is_rapid_approach"):
                    msg_parts.append("(RAPIDO AVVICINAMENTO)")
                msg = " - ".join(msg_parts)
                event_logger.log(ev["type"], details=str(ev))
                stats.add_event(ev["type"], msg)
            
            def _log_callback(msg: str):
                if stats:
                    stats.add_log(msg)
            
            collision_config_path = Path("collision_config.json")
            collision_detector = CollisionModule.create_detector(
                on_event=_on_collision_event,
                log_callback=_log_callback,
                collision_config_path=collision_config_path if collision_config_path.exists() else None,
            )
    
    # Person Safety Detector (INDIPENDENTE da CollisionDetector, richiede YOLO)
    person_safety_detector = None
    enable_person_features = enable_person_safety or enable_person_loitering or enable_person_fall
    if enable_person_features:
        if not model:
            print("⚠️  Sicurezza persone richiede YOLO. Abilita 'enable_yolo'.")
        else:
            from modules.features.person_safety_module import PersonSafetyDetector
            # Path già importato all'inizio del file
            
            def _on_person_event(ev: Dict) -> None:
                print(f"[CALLBACK] _on_person_event CHIAMATO! type={ev.get('type')}, person_id={ev.get('person_id')}")
                event_logger.log(ev["type"], details=str(ev))
                stats.add_event(ev["type"], f"Persona {ev.get('person_id')}: {ev.get('type')}")
            
            def _log_callback(msg: str):
                if stats:
                    stats.add_log(msg)
            
            collision_config_path = Path("collision_config.json")
            person_safety_detector = PersonSafetyDetector(
                enable_loitering=enable_person_loitering,
                enable_fall=enable_person_fall,
                on_event=_on_person_event,
                log_callback=_log_callback,
                config_path=collision_config_path if collision_config_path.exists() else None,
            )
    
    # Person-Vehicle Interaction Detector (richiede YOLO con persone e veicoli)
    person_vehicle_interaction_detector = None
    if enable_person_vehicle_interaction:
        if not model:
            print("⚠️  Interazione persona-veicolo richiede YOLO. Abilita 'enable_yolo'.")
        elif not (enable_person_detection and enable_vehicle_detection):
            print("⚠️  Interazione persona-veicolo richiede sia rilevamento persone che veicoli.")
        else:
            from modules.features.person_vehicle_interaction_module import PersonVehicleInteractionDetector
            
            def _on_interaction_event(ev: Dict) -> None:
                print(f"[CALLBACK] _on_interaction_event CHIAMATO! type={ev.get('type')}, person_id={ev.get('person_id')}")
                event_logger.log(ev["type"], details=str(ev))
                stats.add_event(ev["type"], f"Persona {ev.get('person_id')}: interazione con veicoli")
            
            def _log_callback_interaction(msg: str):
                if stats:
                    stats.add_log(msg)
            
            collision_config_path = Path("collision_config.json")
            person_vehicle_interaction_detector = PersonVehicleInteractionDetector(
                on_event=_on_interaction_event,
                log_callback=_log_callback_interaction,
                config_path=collision_config_path if collision_config_path.exists() else None,
            )
    
    # Person Wall Writing Detector (richiede YOLO con persone)
    person_wall_writing_detector = None
    if enable_person_wall_writing:
        if not model:
            print("⚠️  Rilevamento scrittura su muro richiede YOLO. Abilita 'enable_yolo'.")
        elif not enable_person_detection:
            print("⚠️  Rilevamento scrittura su muro richiede rilevamento persone.")
        else:
            from modules.features.person_wall_writing_module import PersonWallWritingDetector
            
            def _on_wall_writing_event(ev: Dict) -> None:
                print(f"[CALLBACK] _on_wall_writing_event CHIAMATO! type={ev.get('type')}, person_id={ev.get('person_id')}")
                event_logger.log(ev["type"], details=str(ev))
                stats.add_event(ev["type"], f"Persona {ev.get('person_id')}: scrittura su muro")
            
            def _log_callback_wall_writing(msg: str):
                if stats:
                    stats.add_log(msg)
            
            collision_config_path = Path("collision_config.json")
            person_wall_writing_detector = PersonWallWritingDetector(
                on_event=_on_wall_writing_event,
                log_callback=_log_callback_wall_writing,
                config_path=collision_config_path if collision_config_path.exists() else None,
            )
    
    # Flag per tracciare se OpenCV GUI è supportato
    # Verificheremo quando proviamo a usare cv2.imshow()
    opencv_gui_supported = True
    
    # Dashboard disabilitata - ora integrata nel pannello di controllo completo
    dashboard = None
    

    # Crea finestra ridimensionabile per video (se GUI supportata E non c'è frame_callback)
    # Se c'è frame_callback, il video viene mostrato nel pannello di controllo, non serve finestra OpenCV
    video_window_name = "YOLO Tracking - Video Analisi"
    if opencv_gui_supported and not frame_callback:
        try:
            cv2.namedWindow(video_window_name, cv2.WINDOW_NORMAL)  # Ridimensionabile
            # Imposta dimensione iniziale basata su risoluzione video e schermo
            screen_w, screen_h = _get_screen_size()
            max_w = max(screen_w - 100, 640)
            max_h = max(screen_h - 150, 360)
            if width > 0 and height > 0:
                scale = min(max_w / width, max_h / height, 1.0)
                initial_width = int(width * scale)
                initial_height = int(height * scale)
            else:
                initial_width, initial_height = max_w, max_h
            cv2.resizeWindow(video_window_name, initial_width, initial_height)
        except Exception:  # noqa: BLE001
            opencv_gui_supported = False
    elif frame_callback:
        # Se c'è frame_callback, disabilita finestra OpenCV (il video viene mostrato nel pannello)
        opencv_gui_supported = False
    
    stop_event = threading.Event()
    progress_thread = threading.Thread(target=_video_progress_printer, args=(stop_event,), daemon=True)
    progress_thread.start()

    # Calcola classi YOLO in base alle opzioni di rilevamento
    yolo_classes = []
    if enable_person_detection:
        yolo_classes.append(0)  # Person
    if enable_vehicle_detection:
        yolo_classes.extend([2, 3, 5, 7])  # Car, Motorcycle, Bus, Truck
    
    # Se nessuna classe selezionata ma YOLO è abilitato, usa default (persona e auto)
    if not yolo_classes and enable_yolo:
        yolo_classes = [0, 2]  # Default: person and car
        print(f"[DEBUG] analyze_video: Nessuna classe specifica, uso default: {yolo_classes}")
    elif yolo_classes:
        print(f"[DEBUG] analyze_video: Classi YOLO selezionate: {yolo_classes}")
    
    frame_count = 0
    # Per alleggerire analisi collisioni su video, saltiamo più frame
    # Con collision detection: ogni 3 frame (più veloce)
    # Senza collision: ogni frame (massima qualità)
    # Per RTSP con più stream, aumenta frame_skip per ridurre carico
    base_frame_skip = 3 if enable_collision else 1
    if is_rtsp:
        # Per stream RTSP, usa frame_skip più alto per ridurre carico
        # Questo sarà ottimizzato ulteriormente se ci sono più stream simultanei
        frame_skip = max(base_frame_skip, 2)  # Minimo 2 per RTSP
    else:
        frame_skip = base_frame_skip
    paused = False
    
    print(f"[DEBUG] analyze_video: Inizio loop analisi video, frame_skip={frame_skip}, frame_callback={'presente' if frame_callback else 'NON presente'}")
    print(f"[DEBUG] analyze_video: is_rtsp={is_rtsp}, model={'presente' if model else 'NON presente'}")
    
    # Per stream RTSP, attendi un po' per permettere la stabilizzazione della connessione
    if is_rtsp:
        print(f"[DEBUG] analyze_video: Attesa stabilizzazione stream RTSP (2 secondi)...")
        time.sleep(2.0)
        # Prova a leggere alcuni frame iniziali per stabilizzare lo stream
        for i in range(5):
            ret, test_frame = cap.read()
            if ret and test_frame is not None:
                print(f"[DEBUG] analyze_video: Stream RTSP stabilizzato dopo {i+1} tentativi, frame shape: {test_frame.shape}")
                break
            print(f"[DEBUG] analyze_video: Tentativo {i+1}/5 fallito, ret={ret}, test_frame={'None' if test_frame is None else 'presente'}")
            time.sleep(0.2)
        else:
            print(f"[WARNING] analyze_video: Stream RTSP potrebbe non essere ancora pronto, continuo comunque...")

    try:
        print(f"[DEBUG] analyze_video: Entrato nel try block, inizio loop principale")
        consecutive_failures = 0
        max_consecutive_failures = 10  # Per stream RTSP, permette più tentativi falliti
        
        while True:
            # Controlla stop flag (se fornito)
            if stop_flag and stop_flag():
                print("\nStop richiesto dal pannello di controllo.")
                break
            
            # Gestisci comandi dal dashboard
            should_stop, paused = _process_dashboard_commands(dashboard, paused, stats, event_logger)
            if should_stop:
                print("\nStop richiesto dal dashboard.")
                break
            
            if paused:
                # In pausa, aggiorna dashboard e controlla comandi più spesso
                if dashboard:
                    dashboard.update()
                    dashboard.update_display()
                time.sleep(0.05)  # Pausa breve ma lascia tempo a Tkinter
                continue
            
            # Per file video, leggiamo direttamente (NON usiamo FrameBuffer)
            ret, frame = cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                
                # Per stream RTSP, permette più tentativi falliti consecutivi
                if is_rtsp:
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"\n[INFO] Stream RTSP interrotto dopo {consecutive_failures} tentativi falliti. Frame processati: {frame_count}")
                        break
                    # Aspetta un po' prima di riprovare (potrebbe essere un problema temporaneo)
                    time.sleep(0.1)
                    continue
                else:
                    # Per file video, un solo fallimento significa fine del video
                    print(f"\n[INFO] Video terminato. Frame processati: {frame_count}")
                    break
            
            # Reset contatore se abbiamo letto un frame valido
            consecutive_failures = 0
            
            if frame.size == 0:
                print(f"\n[WARNING] Frame vuoto ricevuto. Frame processati: {frame_count}")
                break

            frame_count += 1

            # Salta alcuni frame per ridurre carico (mantiene però il video in uscita)
            if frame_skip > 1 and (frame_count % frame_skip) != 0:
                # scrivi frame originale senza analisi
                out.write(frame)
                if frame_callback:
                    frame_callback(frame)
                continue
            processing_start = time.time()

            # Modalità solo visualizzazione (senza YOLO)
            if not model:
                # Nessun YOLO, solo visualizzazione
                annotated_frame = frame.copy()
                num_cars = 0
                num_persons = 0
                car_ids = []
                person_ids = []
                collision_objects = []
                # IMPORTANTE: Aggiorna statistiche anche senza YOLO (per mantenere FPS e frame count)
                processing_time = time.time() - processing_start
                stats.update_frame(
                    num_cars=0,
                    num_persons=0,
                    car_ids=[],
                    person_ids=[],
                    processing_time=processing_time,
                )
                # Assicura che il frame venga processato anche senza YOLO
                # (stats, collision, ecc. vengono saltati ma il frame viene comunque inviato al callback)
            else:
                # Esegui tracking su questo frame (confidence ridotta per vedere più auto)
                # Ottieni parametri aggiornati se disponibile (real-time)
                current_conf = 0.3  # Default per video file
                current_imgsz = imgsz
                current_classes = yolo_classes  # Usa classi calcolate all'inizio
                if get_params_callback:
                    try:
                        updated_params = get_params_callback()
                        current_conf = updated_params.get("conf", 0.3)
                        current_imgsz = updated_params.get("imgsz", imgsz)
                        # Supporta aggiornamento classi in real-time se disponibile
                        if "enable_person_detection" in updated_params or "enable_vehicle_detection" in updated_params:
                            temp_classes = []
                            if updated_params.get("enable_person_detection", enable_person_detection):
                                temp_classes.append(0)
                            if updated_params.get("enable_vehicle_detection", enable_vehicle_detection):
                                temp_classes.extend([2, 3, 5, 7])
                            if temp_classes:
                                current_classes = temp_classes
                    except:
                        pass  # Usa valori di default se callback fallisce
                
                results = _run_tracking_on_frame(model, frame, conf=current_conf, imgsz=current_imgsz, classes=current_classes)

                # Prendi il primo risultato (frame singolo)
                if not results:
                    out.write(frame)
                    if frame_callback:
                        frame_callback(frame)
                    continue

                result = results[0]
                
                # Ottieni frame annotato base
                # Se collision detection è abilitato, disegniamo manualmente per avere controllo completo sui colori
                if enable_collision:
                    annotated_frame = frame.copy()
                else:
                    annotated_frame = result.plot()

            # Conta auto e persone per statistiche e prepara input per collision detector
            if model:
                num_cars = 0
                num_persons = 0
                car_ids = []
                person_ids = []
                collision_objects = []
                person_objects = []  # Per Person Safety

                # Per ogni detection tracciata, conta oggetti, gestisci targhe e collisioni
                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes
                    masks = None
                    try:
                        if getattr(result, "masks", None) is not None and result.masks.data is not None:
                            # tensor [N, H, W]
                            masks = result.masks.data.cpu().numpy()
                    except Exception:  # noqa: BLE001
                        masks = None

                    # Ottimizzato: usa enumerate invece di range(len())
                    for i, _ in enumerate(boxes):
                        cls, track_id, bbox = _extract_detection_info(boxes, i)
                    
                    if cls is None or track_id is None or bbox is None:
                        continue
                    
                    # Conta per statistiche
                    if cls == 2:  # Car
                        num_cars += 1
                        car_ids.append(track_id)
                        
                        # Filtra oggetti nell'area di esclusione (se configurata)
                        if exclusion_zone:
                            x1, y1, x2, y2 = bbox
                            ex_x1, ex_y1, ex_x2, ex_y2 = exclusion_zone
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2
                            if ex_x1 <= center_x <= ex_x2 and ex_y1 <= center_y <= ex_y2:
                                continue  # Salta oggetti nell'area esclusa
                        
                        # Input per collision detector (con maschera, se disponibile)
                        obj = {
                            "track_id": track_id,
                            "class_id": cls,
                            "bbox": tuple(bbox),
                        }
                        if masks is not None and i < len(masks):
                            obj["mask"] = masks[i] > 0.5
                        collision_objects.append(obj)
                        if plate_manager:
                            x1, y1, x2, y2 = bbox
                            plate_text = plate_manager.get_or_read_plate(
                                frame, (x1, y1, x2, y2), track_id, frame_count
                            )
                            
                            # Aggiungi testo targa al frame
                            if plate_text:
                                label_y = int(y1) - 10 if y1 > 30 else int(y2) + 25
                                label_text = f"Targa: {plate_text}"
                                
                                # Disegna background semitrasparente per il testo
                                (text_width, text_height), _ = cv2.getTextSize(
                                    label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                                )
                                cv2.rectangle(
                                    annotated_frame,
                                    (int(x1), label_y - text_height - 5),
                                    (int(x1) + text_width + 5, label_y + 5),
                                    (0, 0, 0),
                                    -1
                                )
                                cv2.putText(
                                    annotated_frame,
                                    label_text,
                                    (int(x1) + 2, label_y - 2),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6,
                                    (0, 255, 255),  # Giallo
                                    2,
                                )
                    elif cls == 0:  # Person
                        num_persons += 1
                        person_ids.append(track_id)
                        # Passa persone a Person Safety Detector (separato da CollisionDetector)
                        if person_safety_detector:
                            obj = {
                                "track_id": track_id,
                                "class_id": cls,
                                "bbox": tuple(bbox),
                            }
                            person_objects.append(obj)

            # Collision detector (solo veicoli)
            vehicles_in_collision = set()  # Set di track_id coinvolti in collisioni
            collision_pairs_info = []  # Lista di (id1, id2, event_type, details) per disegno linee
            
            # LOG SEMPRE per vedere se collision_objects viene popolato
            print(f"[PROVA_YOLO] Frame {frame_count}: enable_collision={enable_collision}, collision_detector={collision_detector is not None}, collision_objects={len(collision_objects)}")
            
            if enable_collision and collision_detector and collision_objects:
                frame_h, frame_w = frame.shape[:2]
                # Debug: verifica che ci siano veicoli
                print(f"[PROVA_YOLO] Frame {frame_count}: CHIAMO process_frame con {len(collision_objects)} veicoli")
                collision_events = collision_detector.process_frame(
                    camera_id="video_offline",
                    objects=collision_objects,
                    timestamp=time.time(),
                    frame_shape=(frame_h, frame_w),
                )
                # Debug: verifica eventi collisione - LOG SEMPRE
                print(f"[PROVA_YOLO] Frame {frame_count}: process_frame ha restituito {len(collision_events)} eventi")
                if collision_events:
                    print(f"[PROVA_YOLO] ✅ EVENTI COLLISIONE: {len(collision_events)} eventi rilevati!")
                    for idx, ev in enumerate(collision_events):
                        print(f"[PROVA_YOLO]   Evento {idx+1}: type={ev.get('type')}, vehicle_ids={ev.get('vehicle_ids')}")
                else:
                    print(f"[PROVA_YOLO] ❌ NESSUN EVENTO restituito da process_frame")
                # Identifica veicoli coinvolti in collisioni e raccogli info per log/visualizzazione
                for event in collision_events:
                    if "vehicle_ids" in event:
                        vid1, vid2 = event["vehicle_ids"]
                        vehicles_in_collision.update([vid1, vid2])
                        collision_pairs_info.append({
                            "id1": vid1,
                            "id2": vid2,
                            "type": event.get("type", "unknown"),
                            "details": event.get("details", {}),
                            "timestamp": event.get("timestamp", time.time())
                        })
                        
                        # Log collisione per CSV (evita duplicati)
                        if collision_log is not None:
                            pair_key = tuple(sorted([vid1, vid2]))
                            if pair_key not in logged_collision_pairs or (frame_count - logged_collision_pairs[pair_key]) >= 30:
                                logged_collision_pairs[pair_key] = frame_count
                                # Trova bbox dei veicoli per log
                                bbox1 = bbox2 = None
                                for obj in collision_objects:
                                    if obj["track_id"] == vid1:
                                        bbox1 = obj["bbox"]
                                    elif obj["track_id"] == vid2:
                                        bbox2 = obj["bbox"]
                                
                                if bbox1 and bbox2:
                                    timestamp_sec = event.get("timestamp", time.time())
                                    log_entry = {
                                        'frame': frame_count,
                                        'timestamp_sec': round(timestamp_sec, 2),
                                        'time_formatted': f"{int(timestamp_sec // 60):02d}:{int(timestamp_sec % 60):02d}.{int((timestamp_sec % 1) * 100):02d}",
                                        'type': _get_collision_type(event.get("type", "unknown")),
                                        'vehicle1_id': vid1,
                                        'vehicle1_center_x': int((bbox1[0] + bbox1[2]) / 2),
                                        'vehicle1_center_y': int((bbox1[1] + bbox1[3]) / 2),
                                        'vehicle2_id': vid2,
                                        'vehicle2_center_x': int((bbox2[0] + bbox2[2]) / 2),
                                        'vehicle2_center_y': int((bbox2[1] + bbox2[3]) / 2),
                                        'distance': event.get("details", {}).get("distance"),
                                        'iou': event.get("details", {}).get("iou"),
                                        'state1': event.get("details", {}).get("state1"),
                                        'state2': event.get("details", {}).get("state2"),
                                        'approach_rate': event.get("details", {}).get("approach_rate"),
                                        'is_rapid_approach': event.get("details", {}).get("is_rapid_approach"),
                                    }
                                    collision_log.append(log_entry)
            
            # Person Safety Detector (INDIPENDENTE da CollisionDetector)
            if person_safety_detector and person_objects:
                frame_h, frame_w = frame.shape[:2]
                person_events = person_safety_detector.process_persons(
                    camera_id="video_offline",
                    persons=person_objects,
                    timestamp=time.time(),
                    frame_shape=(frame_h, frame_w),
                )
                if person_events:
                    print(f"[PROVA_YOLO] ✅ EVENTI PERSON SAFETY: {len(person_events)} eventi rilevati!")
                    for ev in person_events:
                        print(f"[PROVA_YOLO]   Evento: type={ev.get('type')}, person_id={ev.get('person_id')}")
            
            # Person-Vehicle Interaction Detector
            if person_vehicle_interaction_detector and person_objects and collision_objects:
                frame_h, frame_w = frame.shape[:2]
                interaction_events = person_vehicle_interaction_detector.process_frame(
                    camera_id="video_offline",
                    persons=person_objects,
                    vehicles=collision_objects,
                    timestamp=time.time(),
                    frame_shape=(frame_h, frame_w),
                )
                if interaction_events:
                    print(f"[PROVA_YOLO] ✅ EVENTI PERSON-VEHICLE INTERACTION: {len(interaction_events)} eventi rilevati!")
                    for ev in interaction_events:
                        print(f"[PROVA_YOLO]   Evento: type={ev.get('type')}, person_id={ev.get('person_id')}, vehicles={ev.get('details', {}).get('vehicles_visited')}")
            
            # Person Wall Writing Detector
            if person_wall_writing_detector and person_objects:
                frame_h, frame_w = frame.shape[:2]
                wall_writing_events = person_wall_writing_detector.process_persons(
                    camera_id="video_offline",
                    persons=person_objects,
                    timestamp=time.time(),
                    frame_shape=(frame_h, frame_w),
                )
                if wall_writing_events:
                    print(f"[PROVA_YOLO] ✅ EVENTI WALL WRITING: {len(wall_writing_events)} eventi rilevati!")
                    for ev in wall_writing_events:
                        print(f"[PROVA_YOLO]   Evento: type={ev.get('type')}, person_id={ev.get('person_id')}, wall_side={ev.get('details', {}).get('wall_side')}")
                
                # Disegna tutti gli oggetti (veicoli e persone) con colori personalizzati
                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes
                    # Ottimizzato: usa enumerate invece di range(len())
                    for i, _ in enumerate(boxes):
                        cls, track_id, bbox = _extract_detection_info(boxes, i)
                        if cls is None or track_id is None or bbox is None:
                            continue
                        
                        x1, y1, x2, y2 = bbox
                        
                        # Disegna persone (rosso)
                        if cls == 0:  # Person
                            cv2.rectangle(
                                annotated_frame,
                                (int(x1), int(y1)),
                                (int(x2), int(y2)),
                                (0, 0, 255),  # Rosso BGR
                                2,
                            )
                            # Disegna maschera se disponibile
                            if masks is not None and i < len(masks):
                                _draw_mask(annotated_frame, masks[i], (0, 0, 255), alpha=0.15)
                            # Etichetta con track ID
                            label_id = f"ID:{track_id}"
                            cv2.putText(
                                annotated_frame,
                                label_id,
                                (int(x1), int(y1) - 10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (0, 0, 255),
                                2,
                            )
                            continue
                        
                        # Solo veicoli (cls == 2) continuano
                        if cls != 2:
                            continue
                        
                        is_in_collision = track_id in vehicles_in_collision
                        
                        # Colore: giallo se in collisione, verde se normale
                        color = (0, 255, 255) if is_in_collision else (0, 255, 0)  # Giallo o Verde BGR
                        thickness = 4 if is_in_collision else 2
                        
                        # Disegna maschera se disponibile
                        if masks is not None and i < len(masks):
                            mask = masks[i]
                            _draw_mask(annotated_frame, mask, color, alpha=0.15)
                        
                        # Disegna bounding box
                        cv2.rectangle(
                            annotated_frame,
                            (int(x1), int(y1)),
                            (int(x2), int(y2)),
                            color,
                            thickness,
                        )
                        
                        # Etichetta con track ID
                        label_id = f"ID:{track_id}"
                        cv2.putText(
                            annotated_frame,
                            label_id,
                            (int(x1), int(y1) - 25),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            color,
                            2,
                        )
                        
                        # Etichetta per veicoli in collisione
                        if is_in_collision:
                            label = "COLLISIONE"
                            (text_width, text_height), _ = cv2.getTextSize(
                                label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
                            )
                            cv2.rectangle(
                                annotated_frame,
                                (int(x1), int(y1) - text_height - 10),
                                (int(x1) + text_width + 5, int(y1)),
                                (0, 255, 255),  # Giallo
                                -1
                            )
                            cv2.putText(
                                annotated_frame,
                                label,
                                (int(x1) + 2, int(y1) - 5),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (0, 0, 0),  # Nero
                                2,
                            )
                
                # Disegna linee tra veicoli in collisione e etichette tipo
                for pair_info in collision_pairs_info:
                    vid1, vid2 = pair_info["id1"], pair_info["id2"]
                    # Trova bbox dei veicoli
                    bbox1 = bbox2 = None
                    for obj in collision_objects:
                        if obj["track_id"] == vid1:
                            bbox1 = obj["bbox"]
                        elif obj["track_id"] == vid2:
                            bbox2 = obj["bbox"]
                    
                    if bbox1 and bbox2:
                        # Calcola centri
                        center1 = (int((bbox1[0] + bbox1[2]) / 2), int((bbox1[1] + bbox1[3]) / 2))
                        center2 = (int((bbox2[0] + bbox2[2]) / 2), int((bbox2[1] + bbox2[3]) / 2))
                        
                        # Disegna linea rossa tra i centri
                        cv2.line(annotated_frame, center1, center2, (0, 0, 255), 2)
                        
                        # Etichetta tipo collisione al centro della linea
                        mid_x = int((center1[0] + center2[0]) / 2)
                        mid_y = int((center1[1] + center2[1]) / 2)
                        collision_type = _get_collision_type(pair_info["type"])
                        collision_text = f"COLLISION: {collision_type}"
                        (text_width, text_height), _ = cv2.getTextSize(
                            collision_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                        )
                        # Background per etichetta
                        cv2.rectangle(
                            annotated_frame,
                            (mid_x - text_width // 2 - 5, mid_y - text_height - 5),
                            (mid_x + text_width // 2 + 5, mid_y + 5),
                            (0, 0, 255),  # Rosso
                            -1
                        )
                        cv2.putText(
                            annotated_frame,
                            collision_text,
                            (mid_x - text_width // 2, mid_y + text_height // 2),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (255, 255, 255),  # Bianco
                            2,
                        )

            # Calcola tempo elaborazione
            processing_time = time.time() - processing_start
            
            # Aggiorna statistiche
            stats.update_frame(
                num_cars=num_cars,
                num_persons=num_persons,
                car_ids=car_ids,
                person_ids=person_ids,
                processing_time=processing_time,
            )
            
            # Disegna area di esclusione se configurata
            if exclusion_zone:
                ex_x1, ex_y1, ex_x2, ex_y2 = [int(c) for c in exclusion_zone]
                cv2.rectangle(annotated_frame, (ex_x1, ex_y1), (ex_x2, ex_y2), (128, 128, 128), 2)
                cv2.putText(annotated_frame, "EXCLUDED", (ex_x1, ex_y1 - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)
            
            # Aggiungi overlay con statistiche
            stats_data = stats.get_stats()
            annotated_frame = _draw_stats_overlay(
                annotated_frame, stats_data, num_cars, num_persons, frame_count, total_frames
            )
            
            # Screenshot se richiesto
            _handle_screenshot_command(dashboard, annotated_frame, frame_count, event_logger, stats)
            
            # Se c'è un callback (pannello), invia sempre frame al callback
            if frame_callback:
                try:
                    if frame_count == 1 or frame_count % 30 == 0:
                        print(f"[DEBUG] Chiamata frame_callback per frame {frame_count}")
                    result = frame_callback(annotated_frame)
                    # Se callback restituisce False, ferma elaborazione
                    if result is False:
                        print("\nStop richiesto dal callback.")
                        break
                except Exception as e:
                    print(f"[DEBUG] Errore in frame_callback: {e}")
                    import traceback
                    traceback.print_exc()
                    pass
            
            # Visualizza video in tempo reale (se supportato e non c'è callback)
            if opencv_gui_supported and not frame_callback:
                try:
                    cv2.imshow(video_window_name, annotated_frame)
                    # Gestisci input tastiera (non bloccante)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        print("\nUscita richiesta (tasto 'q')")
                        break
                except Exception as e:  # noqa: BLE001
                    # Se cv2.imshow fallisce, disabilita GUI
                    opencv_gui_supported = False
                    if frame_count == 1:  # Messaggio solo la prima volta
                        print("\nAvviso: OpenCV non supporta la visualizzazione GUI.")
                        print("         Il video verrà elaborato e salvato, ma non mostrato a schermo.")
                        print("         Usa il Dashboard per vedere le statistiche in tempo reale.\n")
            
            # Aggiorna dashboard frequentemente per responsività (Tkinter nel thread principale)
            if dashboard:
                # Aggiorna display ogni 3 frame per buona responsività
                if frame_count % 3 == 0:
                    dashboard.update()  # Processa eventi Tkinter (non bloccante)
                    dashboard.update_display()  # Aggiorna statistiche
                else:
                    # Anche senza aggiornare display, processa eventi Tkinter ogni frame per responsività
                    dashboard.update()
            
            out.write(annotated_frame)

            # Progress update ogni 30 frame
            if frame_count % 30 == 0:
                progress = (frame_count / total_frames * 100) if total_frames > 0 else 0
                print(f"\rFrame {frame_count}/{total_frames} ({progress:.1f}%) - Auto: {num_cars} Persone: {num_persons}", end="", flush=True)

    except Exception as e:  # noqa: BLE001
        print(f"\n[DEBUG] analyze_video: ERRORE durante l'elaborazione del video: {e}")
        import traceback
        print(f"[DEBUG] analyze_video: Traceback completo:")
        traceback.print_exc()
        if stats_collector:
            stats_collector.add_log(f"Errore: {e}")
        cap.release()
        out.release()
        stop_event.set()
        print(f"[DEBUG] analyze_video: RETURN False (errore)")
        return False
    finally:
        print(f"[DEBUG] analyze_video: Entrato nel finally block, frame_count={frame_count}")
        stats.set_status("STOPPED")
        stop_event.set()
        progress_thread.join(timeout=1.0)
        # Rilascia risorse (NON c'è FrameBuffer per file video)
        cap.release()
        out.release()
        print(f"[DEBUG] analyze_video: Risorse rilasciate, funzione terminata")
        
        # Salva log eventi
        if event_logger:
            event_logger.log("video_completed", details=f"Frame processati: {frame_count}")
            event_logger.save()
            print(f"\nLog eventi salvato in: {log_file.resolve()}")
        
        # Salva log CSV collisioni
        if enable_collision and collision_log and len(collision_log) > 0:
            csv_path = video_path.parent / f"{video_path.stem}_collision_log.csv"
            try:
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=collision_log[0].keys())
                    writer.writeheader()
                    writer.writerows(collision_log)
                print(f"Log collisioni CSV salvato in: {csv_path}")
                print(f"Totale eventi collisione unici: {len(collision_log)}")
            except Exception as e:
                print(f"Errore salvataggio log CSV: {e}")
        elif enable_collision and (not collision_log or len(collision_log) == 0):
            print("Nessuna collisione rilevata, log CSV non creato")
        
        # Chiudi finestre OpenCV (se GUI supportata)
        if opencv_gui_supported:
            try:
                cv2.destroyAllWindows()
            except Exception:  # noqa: BLE001
                pass  # Ignora errore se GUI non supportata
        
        # Chiudi dashboard
        if dashboard:
            dashboard.on_closing()

    stats_final = stats.get_stats()
    plate_cache = plate_manager.get_all_plates() if plate_manager else {}
    
    print(f"\n{'='*60}")
    print("ANALISI VIDEO COMPLETATA")
    print(f"{'='*60}")
    print(f"Frame processati: {frame_count}")
    print(f"FPS medio: {stats_final['avg_fps']:.1f}")
    print(f"Targhe lette: {len(plate_cache)}")
    print(f"Totale auto viste: {stats_final['total_cars_seen']}")
    print(f"Totale persone viste: {stats_final['total_persons_seen']}")
    if len(plate_cache) > 0:
        print("\nTarghe trovate:")
        for track_id, plate in plate_cache.items():
            print(f"  Auto ID {track_id}: {plate}")
    print(f"\nVideo annotato salvato in: {output_path.resolve()}")
    print(f"{'='*60}\n")
    return True


def open_video_stream(source: str) -> Optional[cv2.VideoCapture]:
    """
    Apre uno stream video supportando RTSP, HTTP, webcam e file video.
    Rileva automaticamente il tipo di sorgente.
    
    Args:
        source: Sorgente video (RTSP URL, HTTP URL, webcam index come stringa, o path file)
        
    Returns:
        VideoCapture object oppure None se errore
    """
    cap = None
    
    # Rileva tipo sorgente
    source_lower = source.lower().strip()
    
    if source_lower.startswith("rtsp://"):
        # RTSP stream
        print(f"Apertura stream RTSP: {source}")
        print("Attendere connessione (può richiedere fino a 60 secondi)...")
        # Per RTSP, configurare opzioni FFmpeg per timeout più lungo e migliore connessione
        # Timeout aumentato a 60 secondi, TCP per maggiore stabilità
        # Nota: OpenCV/FFmpeg può richiedere opzioni passate come array numpy o come parte dell'URL
        # Proviamo prima con TCP nell'URL stesso per maggiore compatibilità
        rtsp_url = source
        if '?rtsp_transport=' not in rtsp_url.lower():
            separator = '&' if '?' in rtsp_url else '?'
            rtsp_url = f"{rtsp_url}{separator}rtsp_transport=tcp"
        
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Buffer minimo per real time
        # Aspetta un po' per la connessione e verifica
        time.sleep(1.0)
        
        # Verifica connessione tentando di leggere proprietà
        if cap.isOpened():
            # Prova a leggere la larghezza per verificare che lo stream sia attivo
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            if width > 0:
                print(f"✓ Stream connesso (risoluzione: {int(width)}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})")
            else:
                print("⚠ Stream aperto ma potrebbe non essere ancora pronto...")
        
    elif source_lower.startswith("http://") or source_lower.startswith("https://"):
        # HTTP stream (es. Motion JPEG)
        print(f"Apertura stream HTTP: {source}")
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
    elif source.isdigit():
        # Webcam (indice numerico)
        cam_index = int(source)
        print(f"Apertura webcam {cam_index}")
        cap = cv2.VideoCapture(cam_index)
        
    else:
        # File video (o path che potrebbe essere un file)
        video_path = Path(source)
        if video_path.is_file():
            print(f"Apertura file video: {source}")
            cap = cv2.VideoCapture(str(video_path))
        else:
            print(f"Errore: sorgente non riconosciuta o file non trovato: {source}")
            return None
    
    if cap is None or not cap.isOpened():
        print(f"Errore: impossibile aprire la sorgente video: {source}")
        return None
    
    return cap


def run_realtime_stream(
    source: str,
    model_name: str = "yolo11n.pt",
    enable_plates: bool = False,
    enable_collision: bool = False,
    conf: float = 0.6,
    imgsz: int = 1280,
    ) -> bool:
    """
    Esegue tracking real time su uno stream video (RTSP/HTTP/webcam/file).
    
    Args:
        source: Sorgente video (RTSP URL, HTTP URL, webcam index, o path file)
        model_name: Modello YOLO da usare
        enable_plates: Se True, abilita lettura targhe (più lento)
        conf: Soglia di confidenza per detection (default 0.6)
        imgsz: Dimensione input per YOLO (default 1280 per migliore accuratezza)
        
    Returns:
        True se completato con successo, False in caso di errore
    """
    # Carica modello YOLO
    from modules.detection.yolo_module import YOLOModule
    model = YOLOModule.get_model(model_name)
    if model is None:
        print(f"Errore: impossibile caricare il modello YOLO '{model_name}'")
        return False
    
    # Apri stream
    cap = open_video_stream(source)
    if cap is None:
        return False
    
    # Crea FrameBuffer per separare lettura/elaborazione
    # Usa buffer più grande per stream live (10 frame) per gestire meglio i lag
    frame_buffer = FrameBuffer(cap, maxsize=10)
    frame_buffer.start()
    
    # Configura lettura targhe se richiesta
    ocr_reader = None
    if enable_plates:
        from modules.features.ocr_module import OCRModule
        ocr_reader = OCRModule.get_reader()
        if ocr_reader is None:
            print("Avviso: EasyOCR non disponibile, lettura targhe disabilitata")
            enable_plates = False
    
    print(f"\n{'='*60}")
    print("STREAMING REAL TIME - Tracking YOLO")
    print(f"{'='*60}")
    print(f"Sorgente: {source}")
    print(f"Modello: {model_name}")
    print(f"Risoluzione YOLO: {imgsz}px")
    print(f"Lettura targhe: {'ABILITATA' if enable_plates else 'DISABILITATA'}")
    
    # Avviso se è Sub Stream (risoluzione più bassa)
    if "/Channels/" in source:
        # Controlla se è Sub Stream (canale finisce con 2) o Main Stream (finisce con 1)
        match = re.search(r'/Channels/(\d+)$', source)
        if match:
            channel_num = int(match.group(1))
            stream_digit = channel_num % 10
            if stream_digit == 2:
                print(f"\n{'!'*60}")
                print("ATTENZIONE: Stai usando SUB STREAM (risoluzione bassa)")
                print(f"{'!'*60}")
                print("Per migliore accuratezza, usa MAIN STREAM (canale finisce con ...1)")
                print("Sub Stream tipicamente: 640x480 o 800x600")
                print("Main Stream tipicamente: 1920x1080 o superiore")
                print(f"{'!'*60}")
    
    print(f"\nControlli:")
    print("  [q] - Esci")
    print("  [s] - Screenshot (salva frame corrente)")
    print("  [p] - Pause/Resume")
    print(f"{'='*60}\n")
    
    # Variabili per tracking e performance
    frame_count = 0
    fps_start_time = time.time()
    fps_counter = 0
    current_fps = 0.0
    paused = False
    
    # Cache per targhe (se abilitate)
    plate_cache: Dict[int, str] = {}

    # Collision detector opzionale (solo logging su console in streaming)
    collision_detector = None
    if enable_collision:
        def _on_collision_stream(ev: Dict) -> None:
            # LOG SEMPRE per vedere se callback viene chiamato
            print(f"[CALLBACK] _on_collision_stream CHIAMATO! type={ev.get('type')}, vehicle_ids={ev.get('vehicle_ids')}")
            details = ev.get("details", {})
            msg = f"\n[COLLISION] {ev['type']} tra auto {ev['vehicle_ids']} (cam={ev['camera_id']})"
            if details.get("approach_rate") is not None:
                msg += f" - Avvicinamento: {details['approach_rate']*100:.1f}%"
            if details.get("vehicle1_started_moving") or details.get("vehicle2_started_moving"):
                msg += " - Veicolo fermo ha iniziato a muoversi!"
            if details.get("is_rapid_approach"):
                msg += " - RAPIDO AVVICINAMENTO!"
            print(msg)
        # Crea collision detector con log callback
        def _log_callback(msg: str):
            if stats:
                stats.add_log(msg)
        
        collision_detector = CollisionDetector(on_event=_on_collision_stream, log_callback=_log_callback)

    # Controllo FPS dinamico: meno FPS quando c'è poca attività, di più quando
    # ci sono molte auto/persone in scena.
    idle_fps = 3.0       # FPS da usare quando il parcheggio è “calmo”
    active_fps = 10.0    # FPS da usare quando c'è attività
    target_fps = idle_fps
    last_process_time = 0.0
    activity_score = 0.0  # media mobile del numero di oggetti (auto+persone)
    
    # Crea finestra ridimensionabile per video
    window_name = "YOLO Real-Time Tracking"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)  # WINDOW_NORMAL = ridimensionabile dall'utente
    
    # Imposta dimensione iniziale proporzionata alla risoluzione dello schermo
    # mantenendo l'aspect ratio dello stream e senza superare lo schermo.
    try:
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    except Exception:  # noqa: BLE001
        frame_width, frame_height = 1280, 720
    
    screen_w, screen_h = _get_screen_size()
    # Lascia un po' di margine per bordi/barre
    max_w = max(screen_w - 100, 640)
    max_h = max(screen_h - 150, 360)
    
    scale = min(max_w / frame_width, max_h / frame_height, 1.0)
    initial_width = int(frame_width * scale)
    initial_height = int(frame_height * scale)
    cv2.resizeWindow(window_name, initial_width, initial_height)
    
    try:
        while True:
            if not paused:
                # Usa FrameBuffer invece di cap.read() diretto
                frame_data = frame_buffer.read()
                
                if frame_data is None:
                    # Nessun frame disponibile, aspetta un po'
                    time.sleep(0.01)
                    continue
                
                frame, frame_timestamp = frame_data
                
                if frame is None or frame.size == 0:
                    print("\nFrame non valido ricevuto.")
                    # Per stream RTSP/HTTP, prova a riconnettersi
                    if source.startswith("rtsp://") or source.startswith("http://"):
                        print("Tentativo di riconnessione...")
                        time.sleep(2)
                        frame_buffer.stop()
                        cap.release()
                        cap = open_video_stream(source)
                        if cap is None:
                            break
                        frame_buffer = FrameBuffer(cap, maxsize=10)
                        frame_buffer.start()
                        continue
                    else:
                        break
                
                # Controllo FPS dinamico: limita quante volte eseguiamo YOLO
                now = time.time()
                min_interval = 1.0 / max(target_fps, 0.1)
                if (now - last_process_time) < min_interval:
                    # Salta questo frame per alleggerire (ma mantieni la
                    # possibilità di riconnettersi in caso di errore sopra).
                    continue
                last_process_time = now

                frame_count += 1
                fps_counter += 1

                # Calcola FPS effettivi ogni secondo
                elapsed = time.time() - fps_start_time
                if elapsed >= 1.0:
                    current_fps = fps_counter / elapsed
                    fps_counter = 0
                    fps_start_time = time.time()

                # Esegui tracking
                # Ottieni parametri aggiornati se disponibile (real-time)
                current_conf = conf
                current_imgsz = imgsz
                if get_params_callback:
                    try:
                        updated_params = get_params_callback()
                        current_conf = updated_params.get("conf", conf)
                        current_imgsz = updated_params.get("imgsz", imgsz)
                    except:
                        pass  # Usa valori di default se callback fallisce
                
                results = _run_tracking_on_frame(model, frame, conf=current_conf, imgsz=current_imgsz)

                # Prendi risultato tracking
                if results and len(results) > 0:
                    result = results[0]
                    # Se collision detection è abilitato, disegniamo manualmente per avere controllo completo sui colori
                    if enable_collision:
                        annotated_frame = frame.copy()
                    else:
                        annotated_frame = result.plot()
                else:
                    annotated_frame = frame.copy()

                # Conta oggetti per regolare FPS dinamico e collision detector
                num_cars = 0
                num_persons = 0
                collision_objects = []
                if results and len(results) > 0 and result.boxes is not None:
                    boxes = result.boxes
                    masks = None
                    try:
                        if getattr(result, "masks", None) is not None and result.masks.data is not None:
                            masks = result.masks.data.cpu().numpy()
                    except Exception:  # noqa: BLE001
                        masks = None

                    # Ottimizzato: usa enumerate invece di range(len())
                    for i, _ in enumerate(boxes):
                        cls, track_id, bbox = _extract_detection_info(boxes, i)
                        if cls is None or track_id is None or bbox is None:
                            continue
                        if cls == 2:  # car
                            num_cars += 1
                            # Nota: per streaming, area esclusione può essere aggiunta in futuro
                            obj = {
                                "track_id": track_id,
                                "class_id": cls,
                                "bbox": tuple(bbox),
                            }
                            if masks is not None and i < len(masks):
                                obj["mask"] = masks[i] > 0.5
                            collision_objects.append(obj)
                        elif cls == 0:  # person
                            num_persons += 1

                # Collision detector (solo auto)
                vehicles_in_collision = set()  # Set di track_id coinvolti in collisioni
                collision_pairs_info = []  # Lista di (id1, id2, event_type, details) per disegno linee
                if enable_collision and collision_detector and collision_objects:
                    frame_h, frame_w = frame.shape[:2]
                    collision_events = collision_detector.process_frame(
                        camera_id=source,
                        objects=collision_objects,
                        timestamp=time.time(),
                        frame_shape=(frame_h, frame_w),
                    )
                    # Identifica veicoli coinvolti in collisioni
                    for event in collision_events:
                        if "vehicle_ids" in event:
                            vid1, vid2 = event["vehicle_ids"]
                            vehicles_in_collision.update([vid1, vid2])
                            collision_pairs_info.append({
                                "id1": vid1,
                                "id2": vid2,
                                "type": event.get("type", "unknown"),
                                "details": event.get("details", {}),
                                "timestamp": event.get("timestamp", time.time())
                            })
                    
                    # Disegna tutti gli oggetti (veicoli e persone) con colori personalizzati
                    if result.boxes is not None and len(result.boxes) > 0:
                        boxes = result.boxes
                        for i in range(len(boxes)):
                            cls, track_id, bbox = _extract_detection_info(boxes, i)
                            if cls is None or track_id is None or bbox is None:
                                continue
                            
                            x1, y1, x2, y2 = bbox
                            
                            # Disegna persone (rosso)
                            if cls == 0:  # Person
                                cv2.rectangle(
                                    annotated_frame,
                                    (int(x1), int(y1)),
                                    (int(x2), int(y2)),
                                    (0, 0, 255),  # Rosso BGR
                                    2,
                                )
                                # Disegna maschera se disponibile
                                if masks is not None and i < len(masks):
                                    _draw_mask(annotated_frame, masks[i], (0, 0, 255), alpha=0.15)
                                # Etichetta con track ID
                                label_id = f"ID:{track_id}"
                                cv2.putText(
                                    annotated_frame,
                                    label_id,
                                    (int(x1), int(y1) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5,
                                    (0, 0, 255),
                                    2,
                                )
                                continue
                            
                            # Solo veicoli (cls == 2) continuano
                            if cls != 2:
                                continue
                            
                            is_in_collision = track_id in vehicles_in_collision
                            
                            # Colore: giallo se in collisione, verde se normale
                            color = (0, 255, 255) if is_in_collision else (0, 255, 0)  # Giallo o Verde BGR
                            thickness = 4 if is_in_collision else 2
                            
                            # Disegna maschera se disponibile
                            if masks is not None and i < len(masks):
                                mask = masks[i]
                                _draw_mask(annotated_frame, mask, color, alpha=0.15)
                            
                            # Disegna bounding box
                            cv2.rectangle(
                                annotated_frame,
                                (int(x1), int(y1)),
                                (int(x2), int(y2)),
                                color,
                                thickness,
                            )
                            
                            # Etichetta con track ID
                            label_id = f"ID:{track_id}"
                            cv2.putText(
                                annotated_frame,
                                label_id,
                                (int(x1), int(y1) - 25),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                color,
                                2,
                            )
                            
                            # Etichetta per veicoli in collisione
                            if is_in_collision:
                                label = "COLLISIONE"
                                (text_width, text_height), _ = cv2.getTextSize(
                                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
                                )
                                cv2.rectangle(
                                    annotated_frame,
                                    (int(x1), int(y1) - text_height - 10),
                                    (int(x1) + text_width + 5, int(y1)),
                                    (0, 255, 255),  # Giallo
                                    -1
                                )
                                cv2.putText(
                                    annotated_frame,
                                    label,
                                    (int(x1) + 2, int(y1) - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.7,
                                    (0, 0, 0),  # Nero
                                    2,
                                )
                    
                    # Disegna linee tra veicoli in collisione e etichette tipo
                    for pair_info in collision_pairs_info:
                        vid1, vid2 = pair_info["id1"], pair_info["id2"]
                        # Trova bbox dei veicoli
                        bbox1 = bbox2 = None
                        for obj in collision_objects:
                            if obj["track_id"] == vid1:
                                bbox1 = obj["bbox"]
                            elif obj["track_id"] == vid2:
                                bbox2 = obj["bbox"]
                        
                        if bbox1 and bbox2:
                            # Calcola centri
                            center1 = (int((bbox1[0] + bbox1[2]) / 2), int((bbox1[1] + bbox1[3]) / 2))
                            center2 = (int((bbox2[0] + bbox2[2]) / 2), int((bbox2[1] + bbox2[3]) / 2))
                            
                            # Disegna linea rossa tra i centri
                            cv2.line(annotated_frame, center1, center2, (0, 0, 255), 2)
                            
                            # Etichetta tipo collisione al centro della linea
                            mid_x = int((center1[0] + center2[0]) / 2)
                            mid_y = int((center1[1] + center2[1]) / 2)
                            collision_type = _get_collision_type(pair_info["type"])
                            collision_text = f"COLLISION: {collision_type}"
                            (text_width, text_height), _ = cv2.getTextSize(
                                collision_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                            )
                            # Background per etichetta
                            cv2.rectangle(
                                annotated_frame,
                                (mid_x - text_width // 2 - 5, mid_y - text_height - 5),
                                (mid_x + text_width // 2 + 5, mid_y + 5),
                                (0, 0, 255),  # Rosso
                                -1
                            )
                            cv2.putText(
                                annotated_frame,
                                collision_text,
                                (mid_x - text_width // 2, mid_y + text_height // 2),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.6,
                                (255, 255, 255),  # Bianco
                                2,
                            )

                # Aggiorna “activity_score” come media mobile
                activity_score = 0.8 * activity_score + 0.2 * (num_cars + num_persons)
                # Scegli FPS target in base all'attività
                target_fps = active_fps if activity_score > 3 else idle_fps

                # Aggiungi info overlay (FPS, frame count)
                info_text = f"FPS: {current_fps:.1f} | Frame: {frame_count}"
                cv2.putText(
                    annotated_frame,
                    info_text,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),  # Verde
                    2,
                )
                
                # Aggiungi stato pause
                if paused:
                    pause_text = "PAUSED - Premi [p] per riprendere"
                    text_size = cv2.getTextSize(
                        pause_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2
                    )[0]
                    text_x = (annotated_frame.shape[1] - text_size[0]) // 2
                    cv2.putText(
                        annotated_frame,
                        pause_text,
                        (text_x, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 0, 255),  # Rosso
                        2,
                    )
            else:
                # In pause, mostra frame precedente
                if frame_count == 0:
                    annotated_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                else:
                    # Riprova a leggere frame anche in pause (per aggiornare)
                    frame_data = frame_buffer.read()
                    if frame_data is not None:
                        frame, _ = frame_data
                        if frame is not None and frame.size > 0:
                            annotated_frame = frame.copy()
                        else:
                            continue
                    else:
                        continue
            
            # Display frame (finestra ridimensionabile)
            cv2.imshow(window_name, annotated_frame)
            
            # Gestisci input utente
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord("q"):
                print("\nUscita richiesta dall'utente.")
                break
            elif key == ord("s"):
                # Screenshot
                screenshot_path = Path("screenshot") / f"frame_{frame_count:06d}.jpg"
                screenshot_path.parent.mkdir(exist_ok=True)
                cv2.imwrite(str(screenshot_path), annotated_frame)
                print(f"\nScreenshot salvato: {screenshot_path}")
            elif key == ord("p"):
                paused = not paused
                print(f"\n{'PAUSED' if paused else 'RESUMED'}")
            
    except KeyboardInterrupt:
        print("\n\nInterruzione da tastiera (Ctrl+C)")
    except Exception as e:  # noqa: BLE001
        print(f"\nErrore durante lo streaming: {e}")
        return False
    finally:
        # Ferma il FrameBuffer prima di rilasciare il VideoCapture
        if 'frame_buffer' in locals():
            frame_buffer.stop()
        cap.release()
        cv2.destroyAllWindows()
        print(f"\nStreaming terminato.")
        print(f"Frame processati: {frame_count}")
        if enable_plates and len(plate_cache) > 0:
            print(f"Targhe lette: {len(plate_cache)}")
    
    return True


def main(
    image_filename: Optional[str] = None,
    model_name: str = "yolo11n.pt",
    video_filename: Optional[str] = None,
    enable_plates: bool = False,
    enable_collision: bool = False,
    stream_source: Optional[str] = None,
    conf: float = 0.6,
    imgsz: int = 1280,
) -> None:
    """
    Punto di ingresso principale.
    - image_filename: immagine da analizzare (se None, usa 'foto_parcheggio.jpg').
    - video_filename: video da analizzare (se fornito, viene analizzato il video).
    - stream_source: sorgente per streaming real time (RTSP/HTTP/webcam/file).
    - model_name: modello YOLO da usare (default: 'yolo11n.pt', YOLO11 nano).
    - enable_plates: abilita lettura targhe (più lento, default False).

    Logica:
    - Se viene passato stream_source, avvia streaming real time.
    - Se viene passato un video, analizza il video.
    - Altrimenti analizza un'immagine singola.
    """
    # Priorità 1: Streaming real time
    if stream_source is not None:
        run_realtime_stream(
            source=stream_source,
            model_name=model_name,
            enable_plates=enable_plates,
            enable_collision=enable_collision,
            conf=conf,
            imgsz=imgsz,
        )
        return
    
    # Priorità 2: Analisi video
    if video_filename is not None:
        video_path = Path(video_filename)
        analyze_video(
            video_path=video_path,
            model_name=model_name,
            enable_plates=enable_plates,
            enable_dashboard=True,
            log_file=None,  # Auto-generato
            enable_collision=enable_collision,
            imgsz=imgsz,
        )
        return

    # Priorità 3: Analisi immagine (default)
    if image_filename is None:
        image_filename = "foto_parcheggio.jpg"

    image_path = Path(image_filename)
    analyze_image(image_path=image_path, model_name=model_name)


if __name__ == "__main__":
    # ESEMPI DI UTILIZZO DA RIGA DI COMANDO:
    #
    # Analisi video/file:
    #   python prova_yolo.py --video Video_prova.mp4
    #   python prova_yolo.py --video altro_video.mp4 --enable-plates
    #
    # Streaming real time (telecamera Hikvision):
    #   python prova_yolo.py --rtsp  (usa lo stream RTSP configurato in cima al file)
    #
    # Streaming real time (altre sorgenti):
    #   python prova_yolo.py --stream rtsp://user:pass@192.168.1.100:554/stream1
    #   python prova_yolo.py --stream http://192.168.1.100:8080/video.mjpg
    #   python prova_yolo.py --stream 0  (webcam)
    #   python prova_yolo.py --stream Video_prova.mp4  (file loop)
    #
    # Se non passi argomenti, analizzerà di default 'Video_prova.mp4'

    parser = argparse.ArgumentParser(
        description="Analisi video YOLO11 con tracking e (opzionale) lettura targhe. Supporta RTSP/HTTP streaming real time."
    )
    parser.add_argument(
        "--stream",
        type=str,
        default=None,
        help="Sorgente per streaming real time: RTSP URL (rtsp://...), HTTP URL (http://...), webcam index (0, 1, ...), o path file video",
    )
    parser.add_argument(
        "--rtsp",
        action="store_true",
        help="Apre pannello interattivo per selezionare una telecamera dal NVR (scopre automaticamente le telecamere disponibili)",
    )
    parser.add_argument(
        "--video",
        type=str,
        default="Video_prova.mp4",
        help="Percorso del video da analizzare (default: Video_prova.mp4). Ignorato se --stream è specificato.",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Percorso dell'immagine da analizzare (se impostato e --video/--stream non usati)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n.pt",
        help="Nome del modello YOLO da usare (default: yolo11n.pt)",
    )
    parser.add_argument(
        "--enable-plates",
        action="store_true",
        help="Abilita la lettura targhe (può rallentare l'elaborazione)",
    )
    parser.add_argument(
        "--enable-collision",
        action="store_true",
        help="Abilita il rilevamento collisioni auto-auto (sperimentale).",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.6,
        help="Soglia di confidenza per detection (default: 0.6). Usato solo per streaming real time.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=1280,
        help="Dimensione input per YOLO (default: 1280). Usato solo per streaming real time. Valori comuni: 640, 960, 1280, 1920. Valori più alti = migliore accuratezza ma più lento.",
    )

    args = parser.parse_args()

    # Se --rtsp è specificato, mostra pannello selezione telecamere
    stream_source = args.stream
    if args.rtsp:
        selected_url = select_camera_interactive()
        if selected_url:
            stream_source = selected_url
        else:
            print("Nessuna telecamera selezionata. Uscita.")
            sys.exit(0)

    # Chiamata a main con tutti i parametri
    # Priorità: stream > video > image
    main(
        image_filename=args.image,
        model_name=args.model,
        video_filename=None if stream_source else args.video,
        enable_plates=args.enable_plates,
        enable_collision=args.enable_collision,
        stream_source=stream_source,
        conf=args.conf,
        imgsz=args.imgsz,
    )