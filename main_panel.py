"""
Pannello di controllo completo per analisi video con collision detection.
Include dashboard integrata, controlli interattivi e visualizzazione in tempo reale.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import threading
import subprocess
import json
from pathlib import Path
import os
import queue
from datetime import datetime
import cv2
from PIL import Image, ImageTk
import numpy as np


class CompleteControlPanel:
    # Soluzione problema import ciclico FrameBuffer (ora in modulo)
    try:
        from modules.utils.frame_buffer import FrameBuffer
    except ImportError:
        pass # Verrà importato quando serve

    def __init__(self, root):
        self.root = root
        self.root.title("🎥 AI Parking Monitor - Control Center")
        self.root.geometry("1400x900")
        
        # --- CONFIGURAZIONE TEMA GRAFICO MODERNO ---
        self.colors = {
            "bg_dark": "#2E3440",       # Sfondo principale
            "bg_panel": "#3B4252",      # Sfondo pannelli
            "bg_lighter": "#434C5E",    # Elementi in rilievo
            "fg_primary": "#ECEFF4",    # Testo principale
            "fg_secondary": "#D8DEE9",  # Testo secondario
            "accent": "#88C0D0",        # Blu accento
            "success": "#A3BE8C",       # Verde successo
            "warning": "#EBCB8B",       # Giallo warning
            "danger": "#BF616A",        # Rosso errore
            "highlight": "#5E81AC"      # Blu scuro selezione
        }
        
        style = ttk.Style()
        style.theme_use('clam') # Base per personalizzazione completa
        
        # Configurazione Stili Globali
        style.configure(".", 
            background=self.colors["bg_dark"], 
            foreground=self.colors["fg_primary"], 
            font=("Segoe UI", 10)
        )
        
        # Stile Frames
        style.configure("TFrame", background=self.colors["bg_dark"])
        style.configure("Panel.TFrame", background=self.colors["bg_panel"])
        
        # Stile LabelFrames
        style.configure("TLabelframe", 
            background=self.colors["bg_panel"], 
            foreground=self.colors["accent"],
            bordercolor=self.colors["bg_lighter"]
        )
        style.configure("TLabelframe.Label", 
            background=self.colors["bg_panel"], 
            foreground=self.colors["accent"],
            font=("Segoe UI", 11, "bold")
        )
        
        # Stile Label
        style.configure("TLabel", background=self.colors["bg_dark"], foreground=self.colors["fg_primary"])
        style.configure("Panel.TLabel", background=self.colors["bg_panel"], foreground=self.colors["fg_primary"])
        style.configure("Title.TLabel", 
            font=("Segoe UI", 14, "bold"), 
            foreground=self.colors["accent"], 
            background=self.colors["bg_panel"]
        )
        style.configure("Status.TLabel", font=("Consolas", 10), background=self.colors["bg_dark"], foreground=self.colors["success"])

        # Stile Pulsanti (Modern Flat)
        style.configure("TButton", 
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            focuscolor=self.colors["highlight"],
            background=self.colors["bg_lighter"],
            foreground="white"
        )
        style.map("TButton",
            background=[("active", self.colors["highlight"]), ("disabled", self.colors["bg_dark"])],
            foreground=[("disabled", "#666666")]
        )
        
        # Pulsanti Semantici (Action, Danger)
        style.configure("Action.TButton", background=self.colors["success"])
        style.map("Action.TButton", background=[("active", "#8FBCBB"), ("disabled", self.colors["bg_dark"])])
        
        style.configure("Danger.TButton", background=self.colors["danger"])
        style.map("Danger.TButton", background=[("active", "#D08770"), ("disabled", self.colors["bg_dark"])])

        # Stile Notebook (Tabs)
        style.configure("TNotebook", background=self.colors["bg_dark"], borderwidth=0)
        style.configure("TNotebook.Tab", 
            background=self.colors["bg_panel"], 
            foreground=self.colors["fg_secondary"],
            padding=[15, 5],
            font=("Segoe UI", 10)
        )
        style.map("TNotebook.Tab", 
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", self.colors["bg_dark"])],
            expand=[("selected", [1, 1, 1, 0])]
        )
        
        # Checkbox e Radio
        style.configure("TCheckbutton", background=self.colors["bg_panel"], foreground=self.colors["fg_primary"])
        style.map("TCheckbutton", background=[("active", self.colors["bg_panel"])]) # Evita cambio colore on hover
        style.configure("TRadiobutton", background=self.colors["bg_panel"], foreground=self.colors["fg_primary"])

        # Stile Slider (Scale) - Migliorata visibilità
        style.configure("Horizontal.TScale", background=self.colors["bg_panel"])

        # Stile Label specifiche per i valori numerici (evidenziati)
        style.configure("Value.TLabel", 
            font=("Consolas", 10, "bold"), 
            foreground=self.colors["accent"], 
            background=self.colors["bg_panel"]
        )
        
        # Stile Label per descrizioni (più leggibili)
        style.configure("Desc.TLabel", 
            font=("Segoe UI", 9), 
            foreground=self.colors["fg_secondary"], 
            background=self.colors["bg_panel"]
        )

        # Gestione chiusura finestra
        self.root.configure(bg=self.colors["bg_dark"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.video_path = None
        self.processing_process = None
        self.processing_thread = None
        self.stats_thread = None
        self.running = True
        self.should_stop = False  # Flag per fermare analisi video
        
        # Queue per comunicazione thread-safe
        self.command_queue = queue.Queue()
        self.stats_queue = queue.Queue()
        
        # Gestione streaming RTSP multiplo e parametri real-time
        self.active_streams = {}  # Dict {stream_id: {thread, frame_queue, canvas, params_dict, ...}}
        self.stream_counter = 0
        self.realtime_params = {}  # Parametri modificabili in real-time
        self.params_lock = threading.Lock()  # Lock per thread-safe access ai parametri
        self._seen_logs = set()  # Set per log duplicati (ottimizzazione)
        
        # Statistiche
        self.stats = {
            "fps": 0.0,
            "num_cars": 0,
            "num_persons": 0,
            "total_cars": 0,
            "total_persons": 0,
            "frame_count": 0,
            "status": "STOPPED",
            "active_ids": [],
            "events": [],
            "active_streams": 0,
            "collision_events": 0,
            "plates_detected": 0,
            "person_safety_events": 0,
            "start_time": None,
            "elapsed_time": 0
        }
        
        # StatisticsCollector condiviso per stream RTSP (creato quando si avviano gli stream)
        self.rtsp_stats_collector = None
        self.rtsp_stats_thread = None
        
        # Carica configurazione collisione con default dal test project
        self.collision_config_path = Path("config/collision.json")
        self.load_collision_config()
        
        self.setup_ui()
        self.start_stats_updater()
    
    def load_collision_config(self):
        """Carica configurazione collisione da file con default dal test project."""
        # Default dal TEST VIDEO COLLISIONE project
        defaults = {
            "SPEED_MOVING_THRESHOLD": 2.0,  # equivalente a movement_threshold 5.0
            "SPEED_PARKED_THRESHOLD": 0.5,
            "MIN_DIST_THRESHOLD": 100.0,
            "IOU_THRESHOLD": 0.005,  # equivalente a mask_overlap_threshold 0.25 ma più sensibile
            "SPEED_DROP_FACTOR": 0.7,
            "NUDGE_DISTANCE": 2.0,
            "EVENT_DEBOUNCE_SECONDS": 2.0,
            "HISTORY_FRAMES": 5,
            "debug_mode": True,
            "MAX_COLLISION_DISTANCE": 400.0,
            # Parametri aggiuntivi dal test project
            "movement_threshold": 5.0,
            "mask_overlap_threshold": 0.25,
            "size_ratio_threshold": 0.5,
            "y_position_threshold": 0.3,
            "intersection_ratio_threshold": 0.15,
            "enable_perspective_filter": True,
        }
        
        try:
            if self.collision_config_path.exists():
                with open(self.collision_config_path, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    # Unisci default con file config
                    self.collision_config = {**defaults, **file_config}
            else:
                self.collision_config = defaults
                # Salva default
                self.save_collision_config()
        except Exception as e:
            print(f"Errore caricamento config: {e}")
            self.collision_config = defaults
    
    def save_collision_config(self):
        """Salva configurazione collisione su file."""
        try:
            with open(self.collision_config_path, 'w', encoding='utf-8') as f:
                json.dump(self.collision_config, f, indent=2, ensure_ascii=False)
            self.log("Configurazione salvata con successo!")
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile salvare configurazione:\n{e}")
    
    def setup_ui(self):
        """Crea l'interfaccia grafica completa con layout a due colonne."""
        # Frame principale con paned window per dividere sinistra/destra
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill="both", expand=True, padx=5, pady=5)
        
        # === COLONNA SINISTRA: Controlli e Opzioni ===
        left_frame = ttk.Frame(main_paned, width=500)
        main_paned.add(left_frame, weight=0)
        
        # === COLONNA DESTRA: Video e Statistiche ===
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)
        
        # Crea pannello sinistro (controlli)
        self._create_left_panel(left_frame)
        
        # Crea pannello destro (video + stats)
        self._create_right_panel(right_frame)
        
        # Queue per frame video
        self.video_frame_queue = queue.Queue(maxsize=2)  # Mantieni solo ultimi 2 frame
    
        # Carica configurazione telecamere (ora che log_text esiste)
        self.load_cameras_config()
    
    def _create_left_panel(self, parent):
        """Crea pannello sinistro con controlli e opzioni."""
        # Frame principale con scroll migliorato
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Canvas per scroll con bind per mouse wheel
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        # Funzione per aggiornare scroll region
        def update_scroll_region(event=None):
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollable_frame.bind("<Configure>", update_scroll_region)
        
        # Bind mouse wheel per scroll
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Funzione per ridimensionare canvas window quando canvas cambia dimensione
        def configure_canvas_window(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        canvas.bind('<Configure>', configure_canvas_window)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Salva riferimento per cleanup
        self.left_canvas = canvas
        self.left_scrollable_frame = scrollable_frame
        
        # === PULSANTI PRINCIPALI ===
        main_buttons_frame = ttk.LabelFrame(scrollable_frame, text="Operazioni", padding="10")
        main_buttons_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(main_buttons_frame, text="Seleziona Video", 
                  command=self.select_video).pack(fill="x", pady=2)
        
        self.video_path_label = ttk.Label(main_buttons_frame, text="Nessun video selezionato", 
                                          wraplength=400)
        self.video_path_label.pack(fill="x", pady=2)
        
        self.analyze_btn = ttk.Button(main_buttons_frame, text="Analizza Video", 
                                     command=self.start_analysis, state=tk.DISABLED)
        self.analyze_btn.pack(fill="x", pady=2)
        
        # Frame per gestione streaming RTSP
        rtsp_frame = ttk.LabelFrame(scrollable_frame, text="📡 Streaming RTSP - Telecamere", padding="10")
        rtsp_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Pulsanti controllo - organizzati su due righe
        rtsp_buttons_frame = ttk.Frame(rtsp_frame)
        rtsp_buttons_frame.pack(fill="x", pady=5)
        
        # Prima riga: Configurazione e Selezione
        config_row = ttk.Frame(rtsp_buttons_frame)
        config_row.pack(fill="x", pady=(0, 3))
        
        ttk.Button(config_row, text="🔍 Scansiona Rete", 
                  command=self.scan_network_cameras, width=18).pack(side="left", padx=2)
        ttk.Button(config_row, text="🔄 Ricarica Telecamere", 
                  command=self.load_cameras_config, width=20).pack(side="left", padx=2)
        
        # Separatore visivo
        ttk.Separator(config_row, orient="vertical").pack(side="left", fill="y", padx=5)
        
        ttk.Button(config_row, text="☑️ Seleziona Tutto", 
                  command=self.select_all_cameras, width=18).pack(side="left", padx=2)
        ttk.Button(config_row, text="☐ Deseleziona Tutto", 
                  command=self.deselect_all_cameras, width=20).pack(side="left", padx=2)
        
        # Seconda riga: Controllo Streaming (più in evidenza)
        control_row = ttk.Frame(rtsp_buttons_frame)
        control_row.pack(fill="x", pady=(3, 0))
        
        self.start_streaming_btn = ttk.Button(control_row, text="▶️ Avvia Streaming Selezionate", 
                  command=self.start_selected_cameras, state=tk.DISABLED, style="Action.TButton", width=30)
        self.start_streaming_btn.pack(side="left", padx=2, fill="x", expand=True)
        
        self.stop_all_streams_btn = ttk.Button(control_row, text="⏹️ Ferma Tutte le Telecamere", 
                  command=self.stop_all_cameras, state=tk.DISABLED, style="Danger.TButton", width=30)
        self.stop_all_streams_btn.pack(side="left", padx=2, fill="x", expand=True)
        
        # Frame scrollabile per lista telecamere
        cameras_scroll_frame = ttk.Frame(rtsp_frame)
        cameras_scroll_frame.pack(fill="both", expand=True, pady=5)
        
        # Canvas per scroll
        cameras_canvas = tk.Canvas(cameras_scroll_frame, highlightthickness=0)
        cameras_scrollbar = ttk.Scrollbar(cameras_scroll_frame, orient="vertical", command=cameras_canvas.yview)
        cameras_scrollable = ttk.Frame(cameras_canvas)
        
        cameras_scrollable.bind("<Configure>", lambda e: cameras_canvas.configure(scrollregion=cameras_canvas.bbox("all")))
        cameras_canvas.create_window((0, 0), window=cameras_scrollable, anchor="nw")
        cameras_canvas.configure(yscrollcommand=cameras_scrollbar.set)
        
        cameras_canvas.pack(side="left", fill="both", expand=True)
        cameras_scrollbar.pack(side="right", fill="y")
        
        # Bind mouse wheel
        def on_mousewheel_cameras(event):
            cameras_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        cameras_canvas.bind_all("<MouseWheel>", on_mousewheel_cameras)
        
        # Frame per checkbox telecamere
        self.cameras_checkboxes_frame = cameras_scrollable
        
        # Lista telecamere attive
        self.active_cameras_frame = ttk.LabelFrame(scrollable_frame, text="📹 Telecamere Attive", padding="5")
        self.active_cameras_frame.pack(fill="x", padx=5, pady=5)
        
        self.cameras_listbox = tk.Listbox(self.active_cameras_frame, height=4)
        self.cameras_listbox.pack(fill="x", pady=2)
        self.remove_camera_btn = ttk.Button(self.active_cameras_frame, text="Rimuovi Telecamera Selezionata", 
                  command=self.remove_selected_camera, state=tk.DISABLED)
        self.remove_camera_btn.pack(fill="x", pady=2)
        
        # Carica configurazione telecamere (verrà chiamato dopo che log_text è creato)
        self.cameras_config = {}
        self.camera_vars = {}  # Dict {camera_id: tk.BooleanVar}
        
        # === OPZIONI ANALISI ===
        options_frame = ttk.LabelFrame(scrollable_frame, text="🔧 Opzioni Analisi", padding="10")
        options_frame.pack(fill="x", padx=5, pady=5)
        
        # Opzioni separate per rilevamento persone e veicoli
        self.enable_person_detection_var = tk.BooleanVar(value=True)  # Default: True
        self.enable_vehicle_detection_var = tk.BooleanVar(value=False)  # Default: False
        self.enable_yolo_var = tk.BooleanVar(value=False)  # Default: False - YOLO disabilitato di default (si attiva automaticamente se persone o veicoli sono abilitati)
        self.plates_var = tk.BooleanVar(value=False)
        self.collision_var = tk.BooleanVar(value=self.collision_config.get("enable_collision", False))  # Default: False
        self.seg_var = tk.BooleanVar(value=False)  # Default: False (solo flusso video)
        self.person_safety_var = tk.BooleanVar(value=self.collision_config.get("enable_person_safety", False))  # Default: False
        self.person_loiter_var = tk.BooleanVar(value=self.collision_config.get("enable_person_loitering", False))  # Default: False
        self.person_fall_var = tk.BooleanVar(value=self.collision_config.get("enable_person_fall", False))  # Default: False
        self.person_vehicle_interaction_var = tk.BooleanVar(value=self.collision_config.get("enable_person_vehicle_interaction", False))  # Default: False
        self.person_wall_writing_var = tk.BooleanVar(value=self.collision_config.get("enable_person_wall_writing", False))  # Default: False
        self.debug_mode_var = tk.BooleanVar(value=self.collision_config.get("debug_mode", False))  # Default: False
        self.perspective_filter_var = tk.BooleanVar(value=self.collision_config.get("enable_perspective_filter", False))  # Default: False
        self.loiter_seconds_var = tk.DoubleVar(value=self.collision_config.get("LOITER_SECONDS", 20.0))
        self.loiter_radius_var = tk.DoubleVar(value=self.collision_config.get("LOITER_RADIUS", 120.0))
        self.fall_aspect_var = tk.DoubleVar(value=self.collision_config.get("FALL_ASPECT_RATIO", 0.55))
        self.fall_speed_drop_var = tk.DoubleVar(value=self.collision_config.get("FALL_SPEED_DROP", 0.45))
        self.fall_min_height_var = tk.DoubleVar(value=self.collision_config.get("FALL_MIN_HEIGHT", 40.0))
        
        # Separatore visivo
        ttk.Label(options_frame, text="=== Rilevamento Oggetti ===", font=("Arial", 9, "bold")).pack(anchor="w", pady=(0, 5))
        
        # Checkbox separate per persone e veicoli
        person_det_cb = ttk.Checkbutton(options_frame, text="👤 Rileva Persone", 
                       variable=self.enable_person_detection_var)
        person_det_cb.pack(anchor="w", pady=2)
        person_det_cb.configure(command=lambda: self._update_yolo_enable_state())
        
        vehicle_det_cb = ttk.Checkbutton(options_frame, text="🚗 Rileva Veicoli (auto, bus, camion)", 
                       variable=self.enable_vehicle_detection_var)
        vehicle_det_cb.pack(anchor="w", pady=2)
        vehicle_det_cb.configure(command=lambda: self._update_yolo_enable_state())
        
        # Checkbox YOLO (si attiva automaticamente se persone o veicoli sono abilitati, ma può essere disabilitato manualmente)
        self.yolo_cb = ttk.Checkbutton(options_frame, text="🔍 Abilita YOLO (necessario per rilevamento)", 
                       variable=self.enable_yolo_var, state="disabled")  # Inizialmente disabilitato, si abilita se serve
        self.yolo_cb.pack(anchor="w", pady=2)
        self.yolo_cb.configure(command=lambda: self._update_realtime_params("enable_yolo", self.enable_yolo_var.get()))
        
        # Separatore
        ttk.Label(options_frame, text="=== Funzionalità Principali ===", font=("Arial", 9, "bold")).pack(anchor="w", pady=(10, 5))
        
        # Checkbox con callback real-time
        plates_cb = ttk.Checkbutton(options_frame, text="Lettura targhe (EasyOCR)", 
                       variable=self.plates_var)
        plates_cb.pack(anchor="w", pady=2)
        plates_cb.configure(command=lambda: (self._check_and_enable_yolo_if_needed(), self._update_realtime_params("enable_plates", self.plates_var.get())))
        
        collision_cb = ttk.Checkbutton(options_frame, text="Rilevamento collisioni", 
                       variable=self.collision_var)
        collision_cb.pack(anchor="w", pady=2)
        collision_cb.configure(command=lambda: (self._check_and_enable_yolo_if_needed(), self._update_realtime_params("enable_collision", self.collision_var.get())))
        
        seg_cb = ttk.Checkbutton(options_frame, text="Usa modello YOLO-seg (segmentazione)", 
                       variable=self.seg_var)
        seg_cb.pack(anchor="w", pady=2)
        seg_cb.configure(command=lambda: self._update_realtime_params("use_seg", self.seg_var.get()))
        
        # Separatore
        ttk.Label(options_frame, text="=== Sicurezza Persone ===", font=("Arial", 9, "bold")).pack(anchor="w", pady=(10, 5))
        
        # Checkbox sicurezza persone con callback real-time
        person_safety_cb = ttk.Checkbutton(options_frame, text="Sicurezza persone (abilita gruppo)", 
                       variable=self.person_safety_var)
        person_safety_cb.pack(anchor="w", pady=2)
        person_safety_cb.configure(command=lambda: (self._check_and_enable_yolo_if_needed(), self._update_realtime_params("enable_person_safety", self.person_safety_var.get())))
        
        person_loiter_cb = ttk.Checkbutton(options_frame, text="Persone in stazionamento (loitering)", 
                       variable=self.person_loiter_var)
        person_loiter_cb.pack(anchor="w", pady=2)
        person_loiter_cb.configure(command=lambda: self._update_realtime_params("enable_person_loitering", self.person_loiter_var.get()))
        
        person_fall_cb = ttk.Checkbutton(options_frame, text="Caduta persona", 
                       variable=self.person_fall_var)
        person_fall_cb.pack(anchor="w", pady=2)
        person_fall_cb.configure(command=lambda: self._update_realtime_params("enable_person_fall", self.person_fall_var.get()))
        
        person_vehicle_interaction_cb = ttk.Checkbutton(options_frame, text="🚶‍♂️🚗 Monitora persone intorno a veicoli", 
                       variable=self.person_vehicle_interaction_var)
        person_vehicle_interaction_cb.pack(anchor="w", pady=2)
        person_vehicle_interaction_cb.configure(command=lambda: (self._check_and_enable_yolo_if_needed(), self._update_realtime_params("enable_person_vehicle_interaction", self.person_vehicle_interaction_var.get())))
        
        person_wall_writing_cb = ttk.Checkbutton(options_frame, text="✍️ Rileva scrittura su muro", 
                       variable=self.person_wall_writing_var)
        person_wall_writing_cb.pack(anchor="w", pady=2)
        person_wall_writing_cb.configure(command=lambda: (self._check_and_enable_yolo_if_needed(), self._update_realtime_params("enable_person_wall_writing", self.person_wall_writing_var.get())))
        
        # Separatore
        ttk.Label(options_frame, text="=== Opzioni Avanzate ===", font=("Arial", 9, "bold")).pack(anchor="w", pady=(10, 5))
        
        ttk.Checkbutton(options_frame, text="Modalità debug (mostra log dettagliati)", 
                       variable=self.debug_mode_var).pack(anchor="w", pady=2)
        
        # Inizializza lo stato YOLO e i parametri real-time
        self._update_yolo_enable_state()
        ttk.Checkbutton(options_frame, text="Filtro prospettiva (riduce falsi positivi)", 
                       variable=self.perspective_filter_var).pack(anchor="w", pady=2)

        # === Soglie Sicurezza Persone ===
        person_frame = ttk.LabelFrame(scrollable_frame, text="🚶 Sicurezza Persone - Soglie", padding="10")
        person_frame.pack(fill="x", padx=5, pady=5)

        def add_scale(row, label, var, from_, to_, step, fmt, note):
            ttk.Label(person_frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            scale = ttk.Scale(person_frame, from_=from_, to=to_, variable=var, orient=tk.HORIZONTAL)
            scale.grid(row=row, column=1, sticky=tk.W+tk.E, pady=4, padx=5)
            ttk.Label(person_frame, textvariable=tk.StringVar(value=fmt.format(var.get()))).grid(row=row, column=2, sticky=tk.W, padx=5)
            # aggiorna label on move
            def on_move(val, v=var, f=fmt):
                label_var = person_frame.grid_slaves(row=row, column=2)[0]
                label_var.config(text=f.format(float(val)))
            scale.configure(command=on_move)
            ttk.Label(person_frame, text=note, foreground="#B0B0B0").grid(row=row, column=3, sticky=tk.W, padx=5)
            person_frame.columnconfigure(1, weight=1)

        add_scale(
            0, "Loitering: durata (s)",
            self.loiter_seconds_var, 5, 120, 1,
            "{:.0f}s",
            "↑ più tempo richiesto; ↓ rileva prima"
        )
        add_scale(
            1, "Loitering: raggio (px @720p)",
            self.loiter_radius_var, 40, 400, 5,
            "{:.0f}px",
            "↑ tollera movimenti ampi; ↓ più sensibile"
        )
        add_scale(
            2, "Caduta: aspect ratio (w/h)",
            self.fall_aspect_var, 0.4, 1.2, 0.01,
            "{:.2f}",
            "↑ più facile segnalare sdraiato; ↓ più selettivo"
        )
        add_scale(
            3, "Caduta: drop velocità",
            self.fall_speed_drop_var, 0.2, 0.8, 0.01,
            "{:.2f}",
            "↑ richiede calo forte (più preciso); ↓ più permissivo"
        )
        add_scale(
            4, "Caduta: h minima bbox (px)",
            self.fall_min_height_var, 20, 120, 1,
            "{:.0f}px",
            "↑ ignora persone piccole/lontane; ↓ più sensibile"
        )
        
        # === SETTAGGI COLLISION DETECTION ===
        settings_frame = ttk.LabelFrame(scrollable_frame, text="🚗 Settaggi Collision Detection", padding="10")
        settings_frame.pack(fill="x", padx=5, pady=5)
        
        # IOU Threshold (default 0.005)
        ttk.Label(settings_frame, text="IOU Threshold:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.iou_var = tk.DoubleVar(value=self.collision_config.get("IOU_THRESHOLD", 0.005))
        iou_scale = ttk.Scale(settings_frame, from_=0.001, to=0.1, 
                              variable=self.iou_var, orient=tk.HORIZONTAL)
        iou_scale.grid(row=0, column=1, sticky=tk.W+tk.E, pady=5)
        self.iou_label = ttk.Label(settings_frame, text=f"{self.iou_var.get():.4f}")
        self.iou_label.grid(row=0, column=2, padx=5)
        iou_scale.configure(command=lambda v: self.iou_label.config(text=f"{float(v):.4f}"))
        settings_frame.columnconfigure(1, weight=1)
        
        # MIN_DIST_THRESHOLD (default 100.0)
        ttk.Label(settings_frame, text="Min Distanza (px):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.min_dist_var = tk.DoubleVar(value=self.collision_config.get("MIN_DIST_THRESHOLD", 100.0))
        dist_scale = ttk.Scale(settings_frame, from_=20.0, to=200.0, 
                               variable=self.min_dist_var, orient=tk.HORIZONTAL)
        dist_scale.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5)
        self.dist_label = ttk.Label(settings_frame, text=f"{int(self.min_dist_var.get())}")
        self.dist_label.grid(row=1, column=2, padx=5)
        dist_scale.configure(command=lambda v: self.dist_label.config(text=f"{int(float(v))}"))
        
        # SPEED_MOVING_THRESHOLD (default 2.0)
        ttk.Label(settings_frame, text="Soglia Velocità Movimento:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.speed_moving_var = tk.DoubleVar(value=self.collision_config.get("SPEED_MOVING_THRESHOLD", 2.0))
        speed_scale = ttk.Scale(settings_frame, from_=0.5, to=10.0, 
                               variable=self.speed_moving_var, orient=tk.HORIZONTAL)
        speed_scale.grid(row=2, column=1, sticky=tk.W+tk.E, pady=5)
        self.speed_label = ttk.Label(settings_frame, text=f"{self.speed_moving_var.get():.1f}")
        self.speed_label.grid(row=2, column=2, padx=5)
        speed_scale.configure(command=lambda v: self.speed_label.config(text=f"{float(v):.1f}"))
        
        # EVENT_DEBOUNCE_SECONDS (default 2.0)
        ttk.Label(settings_frame, text="Debounce (sec):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.debounce_var = tk.DoubleVar(value=self.collision_config.get("EVENT_DEBOUNCE_SECONDS", 2.0))
        debounce_scale = ttk.Scale(settings_frame, from_=0.5, to=10.0, 
                                   variable=self.debounce_var, orient=tk.HORIZONTAL)
        debounce_scale.grid(row=3, column=1, sticky=tk.W+tk.E, pady=5)
        self.debounce_label = ttk.Label(settings_frame, text=f"{self.debounce_var.get():.1f}")
        self.debounce_label.grid(row=3, column=2, padx=5)
        debounce_scale.configure(command=lambda v: self.debounce_label.config(text=f"{float(v):.1f}"))
        
        # MAX_COLLISION_DISTANCE (default 400.0)
        ttk.Label(settings_frame, text="Max Distanza Collisione:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.max_dist_var = tk.DoubleVar(value=self.collision_config.get("MAX_COLLISION_DISTANCE", 400.0))
        max_dist_scale = ttk.Scale(settings_frame, from_=50.0, to=1000.0, 
                                   variable=self.max_dist_var, orient=tk.HORIZONTAL)
        max_dist_scale.grid(row=4, column=1, sticky=tk.W+tk.E, pady=5)
        self.max_dist_label = ttk.Label(settings_frame, text=f"{int(self.max_dist_var.get())}")
        self.max_dist_label.grid(row=4, column=2, padx=5)
        max_dist_scale.configure(command=lambda v: self.max_dist_label.config(text=f"{int(float(v))}"))
        
        # === METODO GROUND POINT (anti-prospettiva) ===
        ground_point_frame = ttk.LabelFrame(scrollable_frame, text="🎯 Filtro Prospettiva - Ground Point", padding="10")
        ground_point_frame.pack(fill="x", padx=5, pady=5)
        
        # Checkbox per abilitare metodo ground point
        self.use_ground_point_var = tk.BooleanVar(value=self.collision_config.get("use_ground_point_method", True))
        ttk.Checkbutton(ground_point_frame, text="Usa metodo Ground Point (riduce falsi positivi prospettiva)", 
                       variable=self.use_ground_point_var).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Ground Point Distance Threshold
        ttk.Label(ground_point_frame, text="Distanza Ground Point (px):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.gp_dist_var = tk.DoubleVar(value=self.collision_config.get("ground_point_distance_threshold", 50.0))
        gp_dist_scale = ttk.Scale(ground_point_frame, from_=20.0, to=200.0, 
                                  variable=self.gp_dist_var, orient=tk.HORIZONTAL)
        gp_dist_scale.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5)
        self.gp_dist_label = ttk.Label(ground_point_frame, text=f"{int(self.gp_dist_var.get())}")
        self.gp_dist_label.grid(row=1, column=2, padx=5)
        gp_dist_scale.configure(command=lambda v: self.gp_dist_label.config(text=f"{int(float(v))}"))
        ttk.Label(ground_point_frame, text="↑ più permissivo; ↓ più selettivo", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=1, column=3, padx=5, sticky=tk.W)
        ground_point_frame.columnconfigure(1, weight=1)
        
        # Bottom Strip Height Ratio
        ttk.Label(ground_point_frame, text="Altezza Striscia Inferiore (%):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.strip_height_var = tk.DoubleVar(value=self.collision_config.get("bottom_strip_height_ratio", 0.15))
        strip_height_scale = ttk.Scale(ground_point_frame, from_=0.05, to=0.30, 
                                       variable=self.strip_height_var, orient=tk.HORIZONTAL)
        strip_height_scale.grid(row=2, column=1, sticky=tk.W+tk.E, pady=5)
        self.strip_height_label = ttk.Label(ground_point_frame, text=f"{self.strip_height_var.get():.2f}")
        self.strip_height_label.grid(row=2, column=2, padx=5)
        strip_height_scale.configure(command=lambda v: self.strip_height_label.config(text=f"{float(v):.2f}"))
        ttk.Label(ground_point_frame, text="↑ considera più area; ↓ solo base veicolo", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=2, column=3, padx=5, sticky=tk.W)
        
        # Bottom Strip Overlap Ratio
        ttk.Label(ground_point_frame, text="Overlap Strisce Inferiori:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.strip_overlap_var = tk.DoubleVar(value=self.collision_config.get("bottom_strip_overlap_ratio", 0.01))
        strip_overlap_scale = ttk.Scale(ground_point_frame, from_=0.001, to=0.05, 
                                        variable=self.strip_overlap_var, orient=tk.HORIZONTAL)
        strip_overlap_scale.grid(row=3, column=1, sticky=tk.W+tk.E, pady=5)
        self.strip_overlap_label = ttk.Label(ground_point_frame, text=f"{self.strip_overlap_var.get():.4f}")
        self.strip_overlap_label.grid(row=3, column=2, padx=5)
        strip_overlap_scale.configure(command=lambda v: self.strip_overlap_label.config(text=f"{float(v):.4f}"))
        ttk.Label(ground_point_frame, text="↑ più permissivo; ↓ più selettivo", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=3, column=3, padx=5, sticky=tk.W)
        
        # === OPZIONI YOLO ===
        yolo_frame = ttk.LabelFrame(scrollable_frame, text="⚙️ Opzioni YOLO", padding="10")
        yolo_frame.pack(fill="x", padx=5, pady=5)
        
        # Risoluzione YOLO (imgsz) - REAL-TIME
        ttk.Label(yolo_frame, text="Risoluzione YOLO (px):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.imgsz_var = tk.IntVar(value=self.collision_config.get("imgsz", 640))
        imgsz_scale = ttk.Scale(yolo_frame, from_=320, to=1280, 
                               variable=self.imgsz_var, orient=tk.HORIZONTAL)
        imgsz_scale.grid(row=0, column=1, sticky=tk.W+tk.E, pady=5)
        self.imgsz_label = ttk.Label(yolo_frame, text=f"{int(self.imgsz_var.get())}")
        self.imgsz_label.grid(row=0, column=2, padx=5)
        # Callback per aggiornamento real-time
        def update_imgsz(val):
            self.imgsz_label.config(text=f"{int(float(val))}")
            self._update_realtime_params("imgsz", int(float(val)))
        imgsz_scale.configure(command=update_imgsz)
        ttk.Label(yolo_frame, text="🔄 Real-time", font=("Arial", 8), foreground="#A3BE8C").grid(row=0, column=3, padx=5)
        ttk.Label(yolo_frame, text="↑ più preciso (lento); ↓ più veloce", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=0, column=3, padx=5, sticky=tk.W)
        yolo_frame.columnconfigure(1, weight=1)
        
        # Confidence Threshold (nota: usato internamente in _run_tracking_on_frame) - REAL-TIME
        ttk.Label(yolo_frame, text="Confidence Threshold:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.conf_var = tk.DoubleVar(value=self.collision_config.get("conf", 0.3))
        conf_scale = ttk.Scale(yolo_frame, from_=0.1, to=0.9, 
                              variable=self.conf_var, orient=tk.HORIZONTAL)
        conf_scale.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5)
        self.conf_label = ttk.Label(yolo_frame, text=f"{self.conf_var.get():.2f}")
        self.conf_label.grid(row=1, column=2, padx=5)
        # Callback per aggiornamento real-time
        def update_conf(val):
            self.conf_label.config(text=f"{float(val):.2f}")
            self._update_realtime_params("conf", float(val))
        conf_scale.configure(command=update_conf)
        ttk.Label(yolo_frame, text="🔄 Real-time | ↑ più selettivo; ↓ rileva più oggetti", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=1, column=3, padx=5, sticky=tk.W)
        
        # Frame Skip (per performance) - Nota: attualmente hardcoded in analyze_video
        ttk.Label(yolo_frame, text="Frame Skip (info):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.frame_skip_var = tk.IntVar(value=self.collision_config.get("frame_skip", 3))
        frame_skip_scale = ttk.Scale(yolo_frame, from_=1, to=10, 
                                    variable=self.frame_skip_var, orient=tk.HORIZONTAL)
        frame_skip_scale.grid(row=2, column=1, sticky=tk.W+tk.E, pady=5)
        self.frame_skip_label = ttk.Label(yolo_frame, text=f"{int(self.frame_skip_var.get())}")
        self.frame_skip_label.grid(row=2, column=2, padx=5)
        frame_skip_scale.configure(command=lambda v: self.frame_skip_label.config(text=f"{int(float(v))}"))
        ttk.Label(yolo_frame, text="↑ più veloce (salta frame); ↓ più preciso", 
                 font=("Arial", 8), foreground="#B0B0B0").grid(row=2, column=3, padx=5, sticky=tk.W)
        
        # Pulsante salva configurazione
        ttk.Button(settings_frame, text="💾 Salva Configurazione", 
                  command=self.save_settings).grid(row=5, column=0, columnspan=3, pady=10)
        
        # === CONTROLLI DURANTE ANALISI ===
        controls_frame = ttk.LabelFrame(scrollable_frame, text="⏯️ Controlli Analisi", padding="10")
        controls_frame.pack(fill="x", padx=5, pady=5)
        
        self.pause_btn = ttk.Button(controls_frame, text="Pausa", 
                                   command=self.pause_analysis, state=tk.DISABLED)
        self.pause_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(controls_frame, text="Ferma", 
                                  command=self.stop_analysis, state=tk.DISABLED)
        self.stop_btn.pack(side="left", padx=5)
        
        self.screenshot_btn = ttk.Button(controls_frame, text="Screenshot", 
                                        command=self.take_screenshot, state=tk.DISABLED)
        self.screenshot_btn.pack(side="left", padx=5)
    
    def _create_stats_tab_content(self, parent):
        """Crea contenuto tab statistiche."""
        stats_frame = ttk.Frame(parent, padding="10")
        stats_frame.pack(fill="both", expand=True)
        
        # Titolo sezione
        title_label = tk.Label(
            stats_frame, text="📊 Statistiche Real-Time", 
            font=("Arial", 16, "bold"), fg="#2c3e50"
        )
        title_label.pack(pady=(0, 15))
        
        # FPS con icona
        fps_frame = ttk.Frame(stats_frame)
        fps_frame.pack(pady=10)
        tk.Label(fps_frame, text="⚡", font=("Arial", 20)).pack(side=tk.LEFT, padx=5)
        self.fps_label = tk.Label(
            fps_frame, text="FPS: --", font=("Arial", 24, "bold"), fg="#27ae60"
        )
        self.fps_label.pack(side=tk.LEFT)
        
        # Oggetti in scena
        objects_frame = ttk.Frame(stats_frame)
        objects_frame.pack(pady=8)
        tk.Label(objects_frame, text="🚗", font=("Arial", 16)).pack(side=tk.LEFT, padx=5)
        self.objects_label = tk.Label(
            objects_frame, text="Auto: 0 | Persone: 0", font=("Arial", 16)
        )
        self.objects_label.pack(side=tk.LEFT)
        
        # Totale visti
        self.total_label = tk.Label(
            stats_frame, text="Totale Auto: 0 | Totale Persone: 0", 
            font=("Arial", 12), fg="#7f8c8d"
        )
        self.total_label.pack(pady=5)
        
        # Frame processati
        self.frames_label = tk.Label(
            stats_frame, text="Frame: 0", font=("Arial", 12), fg="#7f8c8d"
        )
        self.frames_label.pack(pady=5)
        
        # Stream attivi
        streams_frame = ttk.Frame(stats_frame)
        streams_frame.pack(pady=5)
        tk.Label(streams_frame, text="📡", font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        self.streams_label = tk.Label(
            streams_frame, text="Stream attivi: 0", font=("Arial", 12), fg="#3498db"
        )
        self.streams_label.pack(side=tk.LEFT)
        
        # Tempo di esecuzione
        time_frame = ttk.Frame(stats_frame)
        time_frame.pack(pady=5)
        tk.Label(time_frame, text="⏱️", font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        self.time_label = tk.Label(
            time_frame, text="Tempo: 00:00:00", font=("Arial", 12), fg="#9b59b6"
        )
        self.time_label.pack(side=tk.LEFT)
        
        # Eventi
        events_info_frame = ttk.LabelFrame(stats_frame, text="⚠️ Eventi Rilevati", padding="10")
        events_info_frame.pack(fill="x", pady=5)
        
        events_grid = ttk.Frame(events_info_frame)
        events_grid.pack(fill="x")
        
        # Collisioni
        collision_frame = ttk.Frame(events_grid)
        collision_frame.pack(side=tk.LEFT, padx=10, pady=5)
        tk.Label(collision_frame, text="💥", font=("Arial", 14)).pack()
        self.collision_label = tk.Label(
            collision_frame, text="Collisioni: 0", font=("Arial", 11), fg="#e74c3c"
        )
        self.collision_label.pack()
        
        # Targhe
        plates_frame = ttk.Frame(events_grid)
        plates_frame.pack(side=tk.LEFT, padx=10, pady=5)
        tk.Label(plates_frame, text="🚗", font=("Arial", 14)).pack()
        self.plates_label = tk.Label(
            plates_frame, text="Targhe: 0", font=("Arial", 11), fg="#f39c12"
        )
        self.plates_label.pack()
        
        # Persone a rischio
        safety_frame = ttk.Frame(events_grid)
        safety_frame.pack(side=tk.LEFT, padx=10, pady=5)
        tk.Label(safety_frame, text="👤", font=("Arial", 14)).pack()
        self.safety_label = tk.Label(
            safety_frame, text="Persone a rischio: 0", font=("Arial", 11), fg="#e67e22"
        )
        self.safety_label.pack()
        
        # Stato con colore
        status_frame = ttk.Frame(stats_frame)
        status_frame.pack(pady=15)
        self.status_label = tk.Label(
            status_frame, text="Stato: STOPPED", font=("Arial", 14, "bold"), fg="#e74c3c"
        )
        self.status_label.pack()
        
        # ID attivi
        ids_frame = ttk.LabelFrame(stats_frame, text="🆔 ID Attivi", padding="10")
        ids_frame.pack(fill="both", expand=True, pady=5)
        
        self.ids_text = scrolledtext.ScrolledText(ids_frame, height=8, width=50, font=("Consolas", 9))
        self.ids_text.pack(fill="both", expand=True)
    
    def _create_events_tab_content(self, parent):
        """Crea contenuto tab eventi."""
        events_frame = ttk.Frame(parent, padding="10")
        events_frame.pack(fill="both", expand=True)
        
        self.events_text = scrolledtext.ScrolledText(events_frame, height=30, width=80)
        self.events_text.pack(fill="both", expand=True)
    
    def _create_right_panel(self, parent):
        """Crea pannello destro con video e statistiche."""
        # Paned verticale per dividere video (alto) e stats/log (basso)
        right_paned = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        right_paned.pack(fill="both", expand=True)
        
        # === PARTE ALTA: Video ===
        video_container = ttk.LabelFrame(right_paned, text="📹 Video Live", padding="5")
        right_paned.add(video_container, weight=2)
        
        # Frame per contenere griglia di video (supporto multiplo)
        self.video_grid_frame = ttk.Frame(video_container)
        self.video_grid_frame.pack(fill="both", expand=True)
        
        # Canvas principale per video singolo (compatibilità)
        self.video_canvas = tk.Canvas(self.video_grid_frame, bg="black", width=800, height=600, 
                                     highlightthickness=2, highlightbackground="#34495e")
        self.video_canvas.pack(fill="both", expand=True)
        
        # Label iniziale con stile migliore
        self.video_label = tk.Label(
            self.video_canvas, 
            text="🎥 Video apparirà qui durante l'analisi\n\nSeleziona un video e avvia l'analisi",
            fg="white",
            bg="black",
            font=("Arial", 16, "bold"),
            justify=tk.CENTER
        )
        self.video_canvas.create_window(400, 300, window=self.video_label)
        self.video_started = False
        self.current_video_image = None  # Mantieni riferimento per evitare garbage collection
        
        # === PARTE BASSA: Statistiche e Log (Notebook) ===
        bottom_notebook = ttk.Notebook(right_paned)
        right_paned.add(bottom_notebook, weight=1)
        
        # Tab Statistiche
        stats_tab = ttk.Frame(bottom_notebook)
        bottom_notebook.add(stats_tab, text="📊 Statistiche")
        self._create_stats_tab_content(stats_tab)
        
        # Tab Eventi
        events_tab = ttk.Frame(bottom_notebook)
        bottom_notebook.add(events_tab, text="⚠️ Eventi")
        self._create_events_tab_content(events_tab)
        
        # Tab Log
        log_tab = ttk.Frame(bottom_notebook)
        bottom_notebook.add(log_tab, text="📝 Log")
        self._create_log_tab_content(log_tab)
    
    def _create_log_tab_content(self, parent):
        """Crea contenuto tab log."""
        log_frame = ttk.Frame(parent, padding="10")
        log_frame.pack(fill="both", expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=30, width=80, font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        
        self.log("Pannello di controllo completo avviato.\nSeleziona un video per iniziare.")
    
    def update_video_display(self):
        """Thread per aggiornare display video (usa funzione unificata)."""
        import time
        msg = "[DEBUG] Thread update_video_display avviato"
        print(msg)
        self.root.after(0, lambda: self.log(msg))
        frame_count = 0
        while self.running:
            try:
                if not hasattr(self, 'video_frame_queue'):
                    time.sleep(0.1)
                    continue
                
                latest_frame = None
                # Svuota la coda e tieni solo l'ultimo frame (keep last frame only)
                while not self.video_frame_queue.empty():
                    latest_frame = self.video_frame_queue.get_nowait()

                if latest_frame is not None:
                    frame_count += 1
                    if frame_count == 1 or frame_count % 30 == 0:  # Log ogni 30 frame
                        msg = f"[DEBUG] Display frame {frame_count}, dimensione: {latest_frame.shape}"
                        print(msg)
                        self.root.after(0, lambda: self.log(msg))
                    # Aggiorna UI nel thread principale
                    self.root.after(0, lambda f=latest_frame: self._display_frame_on_canvas(f, self.video_canvas))
                
                time.sleep(0.033)  # ~30 FPS per display
            except Exception as e:
                print(f"[DEBUG] Errore in update_video_display: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
    
    def display_video_frame(self, frame):
        """Compatibilità: inoltra al renderer unificato."""
        self._display_frame_on_canvas(frame, self.video_canvas)
    
    def add_video_frame(self, frame):
        """Aggiunge frame alla queue per visualizzazione (thread-safe)."""
        try:
            if not hasattr(self, 'video_frame_queue'):
                print("[DEBUG] video_frame_queue non esiste ancora!")
                return
            
            if frame is None or frame.size == 0:
                return
            
            if not self.video_frame_queue.full():
                self.video_frame_queue.put_nowait(frame.copy())
            else:
                # Queue piena, scarta frame vecchio
                try:
                    self.video_frame_queue.get_nowait()
                    self.video_frame_queue.put_nowait(frame.copy())
                except queue.Empty:
                    pass
        except Exception as e:
            print(f"[DEBUG] Errore in add_video_frame: {e}")
            import traceback
            traceback.print_exc()
    
    def log(self, message):
        """Aggiunge messaggio al log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        # Verifica che log_text esista (potrebbe non essere ancora creato durante init)
        if hasattr(self, 'log_text') and self.log_text is not None:
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()
        else:
            # Fallback: stampa su console se log_text non esiste ancora
            print(f"[{timestamp}] {message}")
    
    def start_stats_updater(self):
        """Avvia aggiornamento statistiche (ottimizzato - un solo thread)."""
        def update():
            import time
            while self.running:
                try:
                    # Aggiorna statistiche dalla queue (svuota completamente)
                    updated = False
                    try:
                        while True:
                            new_stats = self.stats_queue.get_nowait()
                            self.stats.update(new_stats)
                            updated = True
                    except queue.Empty:
                        pass
                    
                    # Aggiorna UI solo se ci sono stati cambiamenti
                    if updated:
                        self.root.after(0, self.update_stats_display)
                    
                    time.sleep(0.5)  # Aggiorna ogni 500ms
                except Exception:
                    time.sleep(0.5)
        
        self.stats_thread = threading.Thread(target=update, daemon=True)
        self.stats_thread.start()
        
        # Thread per aggiornare video (solo se necessario)
        if hasattr(self, 'video_frame_queue'):
            self.video_thread = threading.Thread(target=self.update_video_display, daemon=True)
            self.video_thread.start()
            print("[DEBUG] Thread video avviato")
        else:
            print("[DEBUG] WARNING: video_frame_queue non esiste, thread video non avviato")
    
    def update_stats_display(self):
        """Aggiorna display statistiche."""
        import time
        
        # Calcola statistiche aggregate da tutti gli stream RTSP attivi
        active_streams_count = len([s for s in self.active_streams.values() if s.get("running", False)])
        
        # Se ci sono stream RTSP attivi, mostra informazioni aggregate
        if active_streams_count > 0:
            # Calcola FPS totale (approssimato)
            total_fps = self.stats.get('fps', 0.0) * active_streams_count if self.stats.get('fps', 0.0) > 0 else 0.0
            self.fps_label.config(text=f"FPS: {total_fps:.1f} ({active_streams_count} stream attivi)")
            # Inizia timer se non già iniziato
            if self.stats.get('start_time') is None:
                self.stats['start_time'] = time.time()
                self.stats['status'] = 'RUNNING'
        else:
            # Usa statistiche dal video file o default
            self.fps_label.config(text=f"FPS: {self.stats.get('fps', 0.0):.1f}")
        
        self.objects_label.config(text=f"Auto: {self.stats.get('num_cars', 0)} | Persone: {self.stats.get('num_persons', 0)}")
        self.total_label.config(text=f"Totale Auto: {self.stats.get('total_cars', 0)} | Totale Persone: {self.stats.get('total_persons', 0)}")
        self.frames_label.config(text=f"Frame: {self.stats.get('frame_count', 0)}")
        
        # Stream attivi
        self.streams_label.config(text=f"Stream attivi: {active_streams_count}")
        
        # Tempo di esecuzione
        if self.stats.get('start_time') is not None:
            elapsed = time.time() - self.stats['start_time']
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.time_label.config(text=f"Tempo: {hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.time_label.config(text="Tempo: 00:00:00")
        
        # Eventi
        self.collision_label.config(text=f"Collisioni: {self.stats.get('collision_events', 0)}")
        self.plates_label.config(text=f"Targhe: {self.stats.get('plates_detected', 0)}")
        self.safety_label.config(text=f"Persone a rischio: {self.stats.get('person_safety_events', 0)}")
        
        # Stato: RUNNING se ci sono stream attivi
        if active_streams_count > 0:
            status = "RUNNING"
        else:
            status = self.stats.get('status', 'STOPPED')
        color = "green" if status == "RUNNING" else "orange" if status == "PAUSED" else "red"
        self.status_label.config(text=f"Stato: {status}", fg=color)
        
        # ID attivi - mostra ID da tutti gli stream
        self.ids_text.delete(1.0, tk.END)
        active_ids = self.stats.get('active_ids', [])
        if active_ids:
            self.ids_text.insert(tk.END, ", ".join(map(str, active_ids)))
        else:
            self.ids_text.insert(tk.END, "Nessun ID attivo")
        
        # Aggiorna eventi
        if hasattr(self, 'events_text'):
            self.events_text.delete(1.0, tk.END)
            events = self.stats.get('events', [])
            if events:
                for event in events[-50:]:  # Ultimi 50 eventi
                    if isinstance(event, dict):
                        timestamp = event.get('timestamp', '')
                        event_type = event.get('type', 'unknown')
                        details = event.get('details', '')
                        line = f"[{timestamp}] {event_type}"
                        if details:
                            line += f": {details}"
                        self.events_text.insert(tk.END, line + "\n")
                    else:
                        self.events_text.insert(tk.END, str(event) + "\n")
            else:
                self.events_text.insert(tk.END, "Nessun evento registrato")
            self.events_text.see(tk.END)
    
    def select_video(self):
        """Apre dialog per selezionare video."""
        # Se c'è un'analisi in corso, fermala prima
        if self.stats['status'] in ['RUNNING', 'PAUSED']:
            self.log("⚠️ Fermando analisi precedente...")
            self.should_stop = True
            # Aspetta che il thread termini (con timeout)
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=2.0)
        
        file_path = filedialog.askopenfilename(
            title="Seleziona Video",
            filetypes=[
                ("Video files", "*.mp4 *.avi *.mov *.mkv *.flv"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            # Reset completo dello stato per nuovo video
            self.should_stop = False
            self.video_started = False
            self.stats['status'] = "STOPPED"
            self.stats['frame_count'] = 0
            self.stats['num_cars'] = 0
            self.stats['num_persons'] = 0
            self.stats['total_cars'] = 0
            self.stats['total_persons'] = 0
            self.stats['active_ids'] = []
            self.stats['events'] = []
            self.stats['fps'] = 0.0
            
            # Reset UI video
            self.video_canvas.delete("all")
            self.video_label = tk.Label(
                self.video_canvas, 
                text="🎥 Video apparirà qui durante l'analisi\n\nSeleziona un video e avvia l'analisi",
                fg="white",
                bg="black",
                font=("Arial", 16, "bold"),
                justify=tk.CENTER
            )
            self.video_canvas.create_window(400, 300, window=self.video_label)
            
            # Aggiorna display statistiche
            self.update_stats_display()
            
            self.video_path = file_path
            filename = os.path.basename(file_path)
            self.video_path_label.config(text=f"Video: {filename}")
            self.analyze_btn.config(state=tk.NORMAL)
            self.log(f"✅ Video selezionato: {filename}")
            self.log("Pronto per l'analisi. Clicca 'Analizza Video' per iniziare.")
    
    def save_settings(self):
        """Salva i settaggi correnti nel file di configurazione."""
        self.collision_config["IOU_THRESHOLD"] = self.iou_var.get()
        self.collision_config["MIN_DIST_THRESHOLD"] = self.min_dist_var.get()
        self.collision_config["SPEED_MOVING_THRESHOLD"] = self.speed_moving_var.get()
        self.collision_config["EVENT_DEBOUNCE_SECONDS"] = self.debounce_var.get()
        self.collision_config["MAX_COLLISION_DISTANCE"] = self.max_dist_var.get()
        self.collision_config["enable_person_safety"] = self.person_safety_var.get()
        self.collision_config["enable_person_loitering"] = self.person_loiter_var.get()
        self.collision_config["enable_person_fall"] = self.person_fall_var.get()
        self.collision_config["enable_person_vehicle_interaction"] = self.person_vehicle_interaction_var.get() if hasattr(self, 'person_vehicle_interaction_var') else False
        self.collision_config["enable_person_wall_writing"] = self.person_wall_writing_var.get() if hasattr(self, 'person_wall_writing_var') else False
        self.collision_config["LOITER_SECONDS"] = self.loiter_seconds_var.get()
        self.collision_config["LOITER_RADIUS"] = self.loiter_radius_var.get()
        self.collision_config["FALL_ASPECT_RATIO"] = self.fall_aspect_var.get()
        self.collision_config["FALL_SPEED_DROP"] = self.fall_speed_drop_var.get()
        self.collision_config["FALL_MIN_HEIGHT"] = self.fall_min_height_var.get()
        self.collision_config["use_ground_point_method"] = self.use_ground_point_var.get()
        self.collision_config["ground_point_distance_threshold"] = self.gp_dist_var.get()
        self.collision_config["bottom_strip_height_ratio"] = self.strip_height_var.get()
        self.collision_config["bottom_strip_overlap_ratio"] = self.strip_overlap_var.get()
        # Nuove opzioni YOLO
        self.collision_config["imgsz"] = int(self.imgsz_var.get())
        self.collision_config["conf"] = self.conf_var.get()
        self.collision_config["frame_skip"] = int(self.frame_skip_var.get())
        self.save_collision_config()
        messagebox.showinfo("Successo", "Configurazione salvata!")
    
    def start_analysis(self):
        """Avvia analisi video."""
        if not self.video_path:
            messagebox.showerror("Errore", "Seleziona prima un video!")
            return
        
        # Se c'è già un'analisi in corso, fermala prima
        if self.stats['status'] in ['RUNNING', 'PAUSED']:
            self.log("⚠️ Fermando analisi precedente...")
            self.should_stop = True
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=2.0)
        
        # Verifica che il file esista
        from pathlib import Path
        video_file = Path(self.video_path)
        if not video_file.exists():
            messagebox.showerror("Errore", f"File video non trovato!\n\nPercorso: {video_file.resolve()}\n\nVerifica che il file esista e sia accessibile.")
            self.log(f"❌ ERRORE: File video non trovato -> {video_file.resolve()}")
            return
        
        if not video_file.is_file():
            messagebox.showerror("Errore", f"Il percorso selezionato non è un file valido!\n\nPercorso: {video_file.resolve()}")
            self.log(f"❌ ERRORE: Il percorso non è un file -> {video_file.resolve()}")
            return
        
        # Reset completo per nuova analisi
        self.should_stop = False  # IMPORTANTE: reset flag
        self.video_started = False
        self.stats['status'] = "STOPPED"
        self.stats['frame_count'] = 0
        self.stats['num_cars'] = 0
        self.stats['num_persons'] = 0
        self.stats['fps'] = 0.0
        
        # Reset UI video
        self.video_canvas.delete("all")
        self.video_label = tk.Label(
            self.video_canvas, 
            text="🎥 Avvio analisi...",
            fg="white",
            bg="black",
            font=("Arial", 16, "bold"),
            justify=tk.CENTER
        )
        self.video_canvas.create_window(400, 300, window=self.video_label)
        
        # Salva settaggi prima di avviare
        self.save_settings()
        
        # Avvia analisi in thread separato con callback per frame
        self.analyze_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        self.screenshot_btn.config(state=tk.NORMAL)
        self.stats['status'] = "RUNNING"
        
        # Assicurati che il thread video sia attivo
        if not hasattr(self, 'video_thread') or not self.video_thread.is_alive():
            if hasattr(self, 'video_frame_queue'):
                self.video_thread = threading.Thread(target=self.update_video_display, daemon=True)
                self.video_thread.start()
                self.log("🔄 Thread video riavviato")
            else:
                self.log("⚠️ WARNING: video_frame_queue non esiste!")
        
        # Thread per analisi video
        self.processing_thread = threading.Thread(
            target=self.run_video_analysis,
            daemon=True
        )
        self.processing_thread.start()
        
        self.log("▶️ Analisi avviata.")
    
    def run_video_analysis(self):
        """Esegue analisi video in thread separato."""
        try:
            from video_analysis import analyze_video
            from modules.core.statistics import StatisticsCollector
            from pathlib import Path
            
            # Verifica che video_path sia ancora valido (potrebbe essere cambiato)
            if not self.video_path:
                self.log("❌ ERRORE: Nessun video selezionato!")
                self.root.after(0, lambda: self.analysis_complete(success=False))
                return
            
            video_path = Path(self.video_path)
            if not video_path.exists():
                self.log(f"❌ ERRORE: Video non trovato: {video_path}")
                self.root.after(0, lambda: self.analysis_complete(success=False))
                return
            
            model_name = "yolo11n-seg.pt" if self.seg_var.get() else "yolo11n.pt"
            
            # Verifica che should_stop non sia True (se lo è, qualcosa è andato storto)
            if self.should_stop:
                self.log("⚠️ Analisi interrotta prima di iniziare (should_stop=True) - reset flag")
                self.should_stop = False  # Reset forzato
            
            self.video_started = False  # Reset anche questo flag
            
            # Crea StatisticsCollector condiviso per ricevere eventi
            shared_stats = StatisticsCollector()
            
            # Thread per aggiornare stats dal StatisticsCollector
            def update_stats_from_collector():
                import time
                while not self.should_stop and self.running:
                    try:
                        stats_data = shared_stats.get_stats()
                        # Aggiorna stats locali
                        self.stats['fps'] = stats_data.get('current_fps', 0.0)
                        self.stats['num_cars'] = stats_data.get('current_objects', {}).get('cars', 0)
                        self.stats['num_persons'] = stats_data.get('current_objects', {}).get('persons', 0)
                        self.stats['total_cars'] = stats_data.get('total_cars_seen', 0)
                        self.stats['total_persons'] = stats_data.get('total_persons_seen', 0)
                        self.stats['frame_count'] = stats_data.get('frame_count', 0)
                        self.stats['status'] = stats_data.get('status', 'STOPPED')
                        self.stats['active_ids'] = stats_data.get('active_track_ids', {}).get('cars', [])
                        self.stats['events'] = stats_data.get('events', [])  # IMPORTANTE: aggiorna eventi
                        
                        # Aggiorna log dalla StatisticsCollector (ottimizzato)
                        logs = stats_data.get('log_messages', [])
                        if logs:
                            # Usa set per controllo duplicati più efficiente
                            if not hasattr(self, '_seen_logs'):
                                self._seen_logs = set()
                            
                            # Aggiungi solo log nuovi
                            new_logs = [log for log in logs if log not in self._seen_logs]
                            if new_logs:
                                for log_msg in new_logs:
                                    self._seen_logs.add(log_msg)
                                    self.log_text.insert(tk.END, f"{log_msg}\n")
                            # Scrolla alla fine
                            self.log_text.see(tk.END)
                            # Limita dimensione set (mantieni ultimi 1000)
                            if len(self._seen_logs) > 1000:
                                self._seen_logs = set(list(self._seen_logs)[-500:])

                    except Exception:
                        pass
            
            stats_updater_thread = threading.Thread(target=update_stats_from_collector, daemon=True)
            stats_updater_thread.start()
            
            # Callback per ricevere frame
            frame_count_callback = [0]  # Usa lista per modificare in closure
            def frame_callback(frame):
                if self.should_stop:
                    return False  # Segnale per fermare
                try:
                    frame_count_callback[0] += 1
                    # Debug: verifica che il frame sia valido
                    if frame is None or frame.size == 0:
                        msg = f"[DEBUG] Frame callback #{frame_count_callback[0]}: frame None o vuoto"
                        print(msg)
                        self.root.after(0, lambda: self.log(msg))
                        return True
                    
                    self.add_video_frame(frame)
                    
                    # Debug: verifica che il frame sia stato aggiunto (solo per i primi frame)
                    if frame_count_callback[0] <= 3 or frame_count_callback[0] % 30 == 0:
                        msg = f"[DEBUG] Frame #{frame_count_callback[0]} ricevuto, queue size: {self.video_frame_queue.qsize()}"
                        print(msg)
                        self.root.after(0, lambda: self.log(msg))
                    
                    return True  # Continua
                except Exception as e:
                    msg = f"[DEBUG] Errore in frame_callback: {e}"
                    print(msg)
                    import traceback
                    traceback.print_exc()
                    self.root.after(0, lambda: self.log(msg))
                    return True  # Continua anche in caso di errore
            
            # Modifica analyze_video per passare stats (temporaneo - meglio sarebbe modificare analyze_video)
            # Per ora, gli eventi vengono passati tramite stats.add_event() che è già chiamato in prova_yolo.py
            # Avvia analisi con callback e stop flag
            # Usa opzioni dal pannello
            imgsz = self._get_optimized_imgsz(int(self.imgsz_var.get()) if hasattr(self, 'imgsz_var') else 640)
            
            # Debug: verifica che tutto sia pronto
            debug_info = f"[DEBUG] Avvio analyze_video:\n"
            debug_info += f"  - video_path: {video_path}\n"
            debug_info += f"  - model_name: {model_name}\n"
            debug_info += f"  - frame_callback presente: {frame_callback is not None}\n"
            debug_info += f"  - video_frame_queue presente: {hasattr(self, 'video_frame_queue')}\n"
            debug_info += f"  - video_thread attivo: {hasattr(self, 'video_thread') and self.video_thread.is_alive() if hasattr(self, 'video_thread') else False}"
            print(debug_info)
            self.log(debug_info)  # Anche nel log del pannello
            self.log("⏳ Caricamento modello YOLO in corso... (può richiedere 10-30 secondi)")
            
            # Configura OCR prima se necessario
            if self.plates_var.get():
                from modules.features.ocr_module import OCRModule
                languages = ['en', 'it'] if self.ocr_lang_var.get() == "en+it" else ['en']
                OCRModule.get_reader(languages=languages, quantize=self.ocr_quant_var.get())

            result = analyze_video(
                video_path=video_path,
                model_name=model_name,
                enable_yolo=self.enable_yolo_var.get() if hasattr(self, 'enable_yolo_var') else False,
                enable_person_detection=self.enable_person_detection_var.get() if hasattr(self, 'enable_person_detection_var') else True,
                enable_vehicle_detection=self.enable_vehicle_detection_var.get() if hasattr(self, 'enable_vehicle_detection_var') else False,
                enable_plates=self.plates_var.get(),
                enable_dashboard=False,  # Dashboard disabilitata, usiamo il pannello
                log_file=None,
                enable_collision=self.collision_var.get(),
                enable_person_safety=self.person_safety_var.get(),
                enable_person_loitering=self.person_loiter_var.get(),
                enable_person_fall=self.person_fall_var.get(),
                enable_person_vehicle_interaction=self.person_vehicle_interaction_var.get() if hasattr(self, 'person_vehicle_interaction_var') else False,
                enable_person_wall_writing=self.person_wall_writing_var.get() if hasattr(self, 'person_wall_writing_var') else False,
                imgsz=imgsz,
                frame_callback=frame_callback,
                stop_flag=lambda: self.should_stop,  # Passa funzione per controllare stop
                stats_collector=shared_stats  # Passa StatisticsCollector condiviso
            )
            
            # Verifica risultato analisi
            if not result:
                error_msg = f"Errore: impossibile analizzare il video.\n\nVerifica che:\n- Il file esista: {video_path}\n- Il formato video sia supportato (MP4, AVI, MOV, etc.)\n- Il file non sia corrotto\n- OpenCV possa leggere il file"
                self.root.after(0, lambda: messagebox.showerror("Errore Analisi", error_msg))
                self.root.after(0, lambda: self.log(f"\n❌ ERRORE: Analisi fallita"))
                self.root.after(0, lambda: self.analysis_complete(success=False))
            else:
                self.root.after(0, lambda: self.log("\n✅ Analisi completata con successo!"))
                self.root.after(0, lambda: self.analysis_complete(success=True))
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Errore", f"Errore durante analisi:\n{e}\n\nDettagli:\n{error_details[:500]}"))
            self.root.after(0, lambda: self.log(f"\n❌ ERRORE: {e}\n{error_details}"))
            self.root.after(0, lambda: self.analysis_complete(success=False))
    
    def read_process_output(self):
        """Legge output del processo in un thread separato (non più usato, mantenuto per compatibilità)."""
        pass
    
    def analysis_complete(self, success: bool = True):
        """Chiamato quando analisi è completata."""
        self.analyze_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.screenshot_btn.config(state=tk.DISABLED)
        self.stats['status'] = "STOPPED"
        self.video_started = False  # Reset per prossima analisi
        
        if success:
            self.log("\n=== ANALISI COMPLETATA CON SUCCESSO ===")
            # Non mostrare messagebox se l'analisi è andata a buon fine (già mostrato messaggio di errore se c'è stato)
        else:
            self.log("\n=== ANALISI INTERROTTA O FALLITA ===")
    
    def pause_analysis(self):
        """Pausa/riprendi analisi."""
        if self.processing_process:
            self.command_queue.put("pause")
            if self.stats['status'] == "RUNNING":
                self.stats['status'] = "PAUSED"
                self.pause_btn.config(text="Riprendi")
            else:
                self.stats['status'] = "RUNNING"
                self.pause_btn.config(text="Pausa")
    
    def stop_analysis(self):
        """Ferma analisi."""
        self.should_stop = True
        self.log("⏹️ Stop richiesto...")
        # Il thread si fermerà quando analyze_video termina
        # Non impostare self.running = False qui, altrimenti blocca tutto il pannello
    
    def take_screenshot(self):
        """Prende screenshot."""
        self.command_queue.put("screenshot")
        self.log("Screenshot richiesto")
    
    def _update_yolo_enable_state(self):
        """Aggiorna lo stato di enable_yolo in base a persone/veicoli selezionati."""
        person_enabled = self.enable_person_detection_var.get()
        vehicle_enabled = self.enable_vehicle_detection_var.get()
        
        # Se almeno uno è selezionato, abilita YOLO
        if person_enabled or vehicle_enabled:
            self.enable_yolo_var.set(True)
            if hasattr(self, 'yolo_cb'):
                self.yolo_cb.config(state="normal")
        else:
            # Se nessuno è selezionato, disabilita YOLO
            self.enable_yolo_var.set(False)
            if hasattr(self, 'yolo_cb'):
                self.yolo_cb.config(state="normal")
        
        # Aggiorna parametri real-time
        self._update_realtime_params("enable_yolo", self.enable_yolo_var.get())
        self._update_realtime_params("enable_person_detection", person_enabled)
        self._update_realtime_params("enable_vehicle_detection", vehicle_enabled)
    
    def _check_and_enable_yolo_if_needed(self):
        """Abilita YOLO automaticamente se necessario (collisioni, targhe, person_safety)."""
        # Verifica se qualche funzionalità che richiede YOLO è abilitata
        needs_yolo = (
            self.plates_var.get() or 
            self.collision_var.get() or 
            self.person_safety_var.get() or
            self.enable_person_detection_var.get() or
            self.enable_vehicle_detection_var.get()
        )
        
        if needs_yolo and not self.enable_yolo_var.get():
            # Abilita YOLO automaticamente
            self.enable_yolo_var.set(True)
            self._update_realtime_params("enable_yolo", True)
            if hasattr(self, 'yolo_cb'):
                self.yolo_cb.config(state="normal")
            self.log("✅ YOLO abilitato automaticamente (richiesto da funzionalità attive)")
    
    def _update_realtime_params(self, param_name, param_value):
        """Aggiorna parametro in real-time per tutti gli stream attivi (ottimizzato)."""
        # Parametri che richiedono il riavvio degli stream (caricamento modelli)
        requires_restart = param_name in [
            "enable_yolo", "enable_plates", "enable_collision", 
            "enable_person_safety", "use_seg", "model_name",
            "enable_person_detection", "enable_vehicle_detection"
        ]
        
        with self.params_lock:
            # Aggiorna parametro globale
            self.realtime_params[param_name] = param_value
            
            # Aggiorna parametro per ogni stream attivo (solo se ha params)
            updated_count = 0
            streams_to_restart = []
            
            for stream_id, stream_info in self.active_streams.items():
                if "params" in stream_info:
                    stream_info["params"][param_name] = param_value
                    updated_count += 1
                    
                    # Se richiede riavvio, aggiungi alla lista
                    if requires_restart:
                        streams_to_restart.append((stream_id, stream_info.get("url")))
            
            # Log solo se ci sono stream attivi
            if updated_count > 0:
                self.log(f"🔄 {param_name}={param_value} (aggiornato per {updated_count} stream)")
            
            # Se richiede riavvio, riavvia gli stream interessati
            if requires_restart and streams_to_restart:
                self.log(f"⚠️ {param_name} richiede riavvio stream per applicare le modifiche...")
                # Riavvia gli stream in un thread separato per non bloccare l'UI
                import threading
                def restart_streams():
                    for stream_id, url in streams_to_restart:
                        try:
                            # Ferma lo stream corrente
                            self.log(f"⏹️ Fermo {stream_id} per riavvio...")
                            if stream_id in self.active_streams:
                                self.active_streams[stream_id]["running"] = False
                                # Attendi che il thread termini
                                if "thread" in self.active_streams[stream_id]:
                                    thread = self.active_streams[stream_id]["thread"]
                                    if thread.is_alive():
                                        thread.join(timeout=2.0)
                            
                            # Rimuovi dall'elenco
                            if stream_id in self.active_streams:
                                del self.active_streams[stream_id]
                            
                            # Riavvia lo stream con i nuovi parametri
                            self.log(f"▶️ Riavvio {stream_id} con nuovi parametri...")
                            self.root.after(100, lambda sid=stream_id, u=url: self._restart_single_stream(sid, u))
                        except Exception as e:
                            self.log(f"❌ Errore riavvio {stream_id}: {e}")
                
                threading.Thread(target=restart_streams, daemon=True).start()
    
    def _get_realtime_params(self, stream_id=None):
        """Ottiene parametri real-time per uno stream specifico o globali (ottimizzato)."""
        with self.params_lock:
            if stream_id and stream_id in self.active_streams:
                # Ritorna parametri specifici dello stream (riferimento diretto, più veloce)
                return self.active_streams[stream_id].get("params", self.realtime_params)
            else:
                # Ritorna parametri globali (copia solo se necessario)
                return self.realtime_params
    
    def _get_optimal_yolo_model(self, params=None):
        """
        Determina il modello YOLO ottimale in base alle funzionalità abilitate.
        
        Args:
            params: Dict con parametri dello stream (opzionale, usa valori di default se None)
        
        Returns:
            Nome del modello YOLO ottimale, o None se non serve YOLO (modalità solo visualizzazione)
        """
        # Se params non fornito, usa valori di default dal pannello
        if params is None:
            enable_yolo = self.enable_yolo_var.get() if hasattr(self, 'enable_yolo_var') else False
            enable_plates = self.plates_var.get() if hasattr(self, 'plates_var') else False
            enable_collision = self.collision_var.get() if hasattr(self, 'collision_var') else False
            enable_person_safety = self.person_safety_var.get() if hasattr(self, 'person_safety_var') else False
        else:
            enable_yolo = params.get("enable_yolo", False)
            enable_plates = params.get("enable_plates", False)
            enable_collision = params.get("enable_collision", False)
            enable_person_safety = params.get("enable_person_safety", False)
        
        # Se collisioni, targhe, person_safety, person_vehicle_interaction o person_wall_writing sono abilitati, YOLO è NECESSARIO
        # quindi abilitalo automaticamente se non già abilitato
        enable_person_vehicle_interaction = params.get("enable_person_vehicle_interaction", False) if params else (self.person_vehicle_interaction_var.get() if hasattr(self, 'person_vehicle_interaction_var') else False)
        enable_person_wall_writing = params.get("enable_person_wall_writing", False) if params else (self.person_wall_writing_var.get() if hasattr(self, 'person_wall_writing_var') else False)
        needs_yolo_for_features = enable_plates or enable_collision or enable_person_safety or enable_person_vehicle_interaction or enable_person_wall_writing
        
        # Se YOLO è esplicitamente disabilitato E tutte le altre funzioni sono disabilitate, non serve YOLO
        if not enable_yolo and not needs_yolo_for_features:
            return None  # analyze_video gestirà la modalità solo visualizzazione
        
        # IMPORTANTE: Se una funzionalità che richiede YOLO è abilitata, 
        # YOLO DEVE essere caricato (anche se enable_yolo era False)
        # Questo permette a collisioni/targhe di funzionare correttamente
        if needs_yolo_for_features:
            # Forza enable_yolo a True se necessario per le funzionalità
            enable_yolo = True
        
        # Usa YOLOModule per determinare il modello ottimale
        from modules.detection.yolo_module import YOLOModule
        
        features = {
            "enable_plates": enable_plates,
            "enable_collision": enable_collision,
            "enable_person_safety": enable_person_safety,
            "enable_yolo": enable_yolo  # Usa il valore reale di enable_yolo
        }
        
        return YOLOModule.get_optimal_model(features)
    
    def _get_optimized_imgsz(self, base_imgsz):
        """Ottimizza la risoluzione YOLO in base al numero di stream attivi per ridurre carico."""
        active_streams_count = len([s for s in self.active_streams.values() if s.get("running", False)])
        
        if active_streams_count >= 3:
            # Con 3+ stream, riduci risoluzione per alleggerire carico
            optimized = min(base_imgsz, 480)  # Max 480 quando ci sono 3+ stream
            if optimized != base_imgsz:
                self.log(f"⚡ Risoluzione YOLO ottimizzata: {base_imgsz} -> {optimized} (3+ stream attivi)")
        elif active_streams_count == 2:
            # Con 2 stream, riduci leggermente
            optimized = min(base_imgsz, 512)
        else:
            # Con 1 stream, usa risoluzione normale
            optimized = base_imgsz
        
        return optimized
    
    def start_rtsp_stream(self):
        """Avvia streaming RTSP (legacy - usa start_rtsp_stream_integrated)."""
        self.start_rtsp_stream_integrated()
    
    def test_rtsp_connection(self):
        """Testa connessione RTSP."""
        url = self.rtsp_url_var.get().strip() if hasattr(self, 'rtsp_url_var') else ""
        if not url:
            messagebox.showwarning("Attenzione", "Inserisci un URL RTSP da testare.")
            return
        
        self.log(f"Testando connessione RTSP: {url.split('@')[0]}@***")
        
        def test_thread():
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        height, width = frame.shape[:2]
                        self.root.after(0, lambda: messagebox.showinfo("Successo", 
                            f"Connessione RTSP riuscita!\nRisoluzione: {width}x{height}"))
                        self.log(f"✅ Connessione RTSP riuscita: {width}x{height}")
                    else:
                        self.root.after(0, lambda: messagebox.showerror("Errore", 
                            "Connesso ma nessun frame disponibile"))
                        self.log("❌ Connesso ma nessun frame disponibile")
                else:
                    self.root.after(0, lambda: messagebox.showerror("Errore", 
                        "Impossibile aprire stream RTSP"))
                    self.log("❌ Impossibile aprire stream RTSP")
                
                cap.release()
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Errore", f"Errore test: {e}"))
                self.log(f"❌ Errore test RTSP: {e}")
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def start_rtsp_stream_integrated(self):
        """Avvia streaming RTSP integrato nel pannello."""
        url = self.rtsp_url_var.get().strip() if hasattr(self, 'rtsp_url_var') else ""
        if not url:
            # Usa URL di default da config
            try:
                rtsp_config = Path("config/rtsp.json")
                if rtsp_config.exists():
                    with open(rtsp_config, 'r') as f:
                        config = json.load(f)
                        ip = config.get("ip", "192.168.1.124")
                        port = config.get("port", "554")
                        user = config.get("user", "User")
                        password = config.get("password", "")
                        from urllib.parse import quote
                        url = f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{ip}:{port}/Streaming/Channels/102"
                else:
                    messagebox.showwarning("Attenzione", 
                        "Inserisci un URL RTSP o configura rtsp_config.json")
                    return
            except Exception as e:
                messagebox.showerror("Errore", f"Errore caricamento config: {e}")
                return
        
        self.add_camera_stream(url)
    
    def add_camera_stream(self, url=None):
        """Aggiunge una nuova telecamera allo streaming."""
        # Crea StatisticsCollector condiviso per stream RTSP se non esiste
        if self.rtsp_stats_collector is None:
            from modules.core.statistics import StatisticsCollector
            self.rtsp_stats_collector = StatisticsCollector()
            self.rtsp_stats_collector.set_status("RUNNING")
            
            # Thread per aggiornare stats dal collector RTSP
            def update_rtsp_stats():
                import time
                while any(s.get("running", False) for s in self.active_streams.values()):
                    try:
                        if self.rtsp_stats_collector:
                            stats_data = self.rtsp_stats_collector.get_stats()
                            # Aggiorna stats locali
                            self.stats['fps'] = stats_data.get('current_fps', 0.0)
                            self.stats['num_cars'] = stats_data.get('current_objects', {}).get('cars', 0)
                            self.stats['num_persons'] = stats_data.get('current_objects', {}).get('persons', 0)
                            self.stats['total_cars'] = stats_data.get('total_cars_seen', 0)
                            self.stats['total_persons'] = stats_data.get('total_persons_seen', 0)
                            self.stats['frame_count'] = stats_data.get('frame_count', 0)
                            self.stats['status'] = stats_data.get('status', 'STOPPED')
                            self.stats['active_ids'] = stats_data.get('active_track_ids', {}).get('cars', [])
                            self.stats['events'] = stats_data.get('events', [])  # IMPORTANTE: aggiorna eventi RTSP
                            
                            # Aggiorna start_time se necessario
                            if self.stats.get('start_time') is None:
                                self.stats['start_time'] = time.time()
                            
                            # Aggiorna display
                            self.root.after(0, self.update_stats_display)
                        
                        time.sleep(0.5)  # Aggiorna ogni 500ms
                    except Exception as e:
                        self.log(f"❌ Errore aggiornamento stats RTSP: {e}")
                        time.sleep(0.5)
            
            # Avvia thread aggiornamento stats RTSP
            if self.rtsp_stats_thread is None or not self.rtsp_stats_thread.is_alive():
                self.rtsp_stats_thread = threading.Thread(target=update_rtsp_stats, daemon=True)
                self.rtsp_stats_thread.start()
        
        if url is None:
            url = self.rtsp_url_var.get().strip() if hasattr(self, 'rtsp_url_var') else ""
            if not url:
                messagebox.showwarning("Attenzione", "Inserisci un URL RTSP.")
                return
        
        stream_id = f"stream_{self.stream_counter}"
        self.stream_counter += 1
        
        self.log(f"Avvio streaming RTSP: {url.split('@')[0]}@***")
        
        # Crea frame queue per questo stream
        frame_queue = queue.Queue(maxsize=2)
        
        # Aggiungi alla lista
        if hasattr(self, 'cameras_listbox'):
            self.cameras_listbox.insert(tk.END, f"{stream_id}: {url.split('@')[0]}@***")
        
        # Avvia thread per questo stream
        stream_thread = threading.Thread(
            target=self._run_stream_thread,
            args=(stream_id, url, frame_queue),
            daemon=True
        )
        stream_thread.start()
        
        # Inizializza parametri per questo stream
        with self.params_lock:
            self.active_streams[stream_id] = {
                "url": url,
                "thread": stream_thread,
                "frame_queue": frame_queue,
                "running": True,
                "params": {
                    "enable_yolo": self.enable_yolo_var.get() if hasattr(self, 'enable_yolo_var') else False,
                    "enable_person_detection": self.enable_person_detection_var.get() if hasattr(self, 'enable_person_detection_var') else True,
                    "enable_vehicle_detection": self.enable_vehicle_detection_var.get() if hasattr(self, 'enable_vehicle_detection_var') else False,
                    "model_name": "yolo11n-seg.pt" if self.seg_var.get() else "yolo11n.pt",
                    "enable_plates": self.plates_var.get(),
                    "enable_collision": self.collision_var.get(),
                    "enable_person_safety": self.person_safety_var.get(),
                    "enable_person_loitering": self.person_loiter_var.get(),
                    "enable_person_fall": self.person_fall_var.get(),
                    "enable_person_vehicle_interaction": self.person_vehicle_interaction_var.get() if hasattr(self, 'person_vehicle_interaction_var') else False,
                    "enable_person_wall_writing": self.person_wall_writing_var.get() if hasattr(self, 'person_wall_writing_var') else False,
                    "imgsz": int(self.imgsz_var.get()) if hasattr(self, 'imgsz_var') else 640,
                    "conf": self.conf_var.get() if hasattr(self, 'conf_var') else 0.6,
                }
            }
        
        # Aggiorna layout video per supporto multiplo (con piccolo delay per permettere al thread di partire)
        # Usa after_idle per assicurarsi che il layout venga aggiornato dopo che tutti i widget sono stati creati
        self.root.after_idle(self._update_video_layout)
    
    def _restart_single_stream(self, stream_id, url):
        """Riavvia un singolo stream con i parametri aggiornati."""
        try:
            # Crea nuovo stream_id (riusa quello vecchio)
            new_stream_id = stream_id
            
            # Crea frame queue per questo stream
            frame_queue = queue.Queue(maxsize=2)
            
            # Aggiorna layout se necessario
            if hasattr(self, 'cameras_listbox'):
                # Rimuovi vecchia entry se esiste
                items = self.cameras_listbox.get(0, tk.END)
                for i, item in enumerate(items):
                    if stream_id in item:
                        self.cameras_listbox.delete(i)
                        break
                # Aggiungi nuova entry
                self.cameras_listbox.insert(tk.END, f"{new_stream_id}: {url.split('@')[0]}@***")
            
            # Avvia thread per questo stream
            stream_thread = threading.Thread(
                target=self._run_stream_thread,
                args=(new_stream_id, url, frame_queue),
                daemon=True
            )
            stream_thread.start()
            
            # Inizializza parametri per questo stream (usa valori aggiornati)
            with self.params_lock:
                self.active_streams[new_stream_id] = {
                    "url": url,
                    "thread": stream_thread,
                    "frame_queue": frame_queue,
                    "running": True,
                    "params": {
                        "enable_yolo": self.enable_yolo_var.get() if hasattr(self, 'enable_yolo_var') else False,
                        "model_name": "yolo11n-seg.pt" if self.seg_var.get() else "yolo11n.pt",
                        "enable_plates": self.plates_var.get(),
                        "enable_collision": self.collision_var.get(),
                        "enable_person_safety": self.person_safety_var.get(),
                        "enable_person_loitering": self.person_loiter_var.get(),
                        "enable_person_fall": self.person_fall_var.get(),
                        "imgsz": int(self.imgsz_var.get()) if hasattr(self, 'imgsz_var') else 640,
                        "conf": self.conf_var.get() if hasattr(self, 'conf_var') else 0.6,
                    }
                }
            
            # Aggiorna layout video
            self.root.after_idle(self._update_video_layout)
            
            self.log(f"✅ Stream {new_stream_id} riavviato con successo")
        except Exception as e:
            self.log(f"❌ Errore riavvio stream {stream_id}: {e}")
            import traceback
            self.log(traceback.format_exc())
        
        # Abilita pulsanti di controllo
        self.stop_all_streams_btn.config(state=tk.NORMAL)
        self.remove_camera_btn.config(state=tk.NORMAL)
    
    def _run_stream_thread(self, stream_id, url, frame_queue):
        """Thread per gestire uno stream RTSP."""
        self.log(f"[DEBUG] {stream_id}: Thread stream avviato, URL: {url.split('@')[0]}@***")
        try:
            import time as time_module
            import os
            _log_path = r"c:\Users\falba\OneDrive - ABIVET-UPVET\Desktop\Test progetti Yolo\.cursor\debug.log"
            _log_dir = os.path.dirname(_log_path)
            if not os.path.exists(_log_dir):
                os.makedirs(_log_dir, exist_ok=True)
            def _write_debug_log(data_str):
                try:
                    with open(_log_path, "a", encoding="utf-8") as f:
                        f.write(data_str)
                        f.flush()
                        os.fsync(f.fileno())
                except Exception as e:
                    try:
                        error_msg = f"[DEBUG LOG ERROR] {e}"
                        self.log(error_msg)
                        print(error_msg)
                    except:
                        print(f"[DEBUG LOG ERROR] {e}")
            # Test write to verify file can be created
            try:
                test_msg = f'{{"id":"test_init","timestamp":{int(time_module.time()*1000)},"message":"INIT TEST","sessionId":"debug-session"}}\n'
                _write_debug_log(test_msg)
                print(f"[DEBUG] Log file initialized at: {_log_path}")
            except Exception as e:
                print(f"[DEBUG] FAILED to initialize log file: {e}")
            # #region agent log
            try:
                _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_thread_start","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1659","message":"_run_stream_thread STARTED","data":{{"stream_id":"{stream_id}","url_present":{url is not None}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
            except Exception as e:
                print(f"[DEBUG LOG ERROR] {e}")
            # #endregion
            from video_analysis import analyze_video  # Usa analyze_video che supporta frame_callback
            
            self.log(f"[DEBUG] {stream_id}: Thread stream avviato, URL: {url.split('@')[0]}@***")
            
            # Callback per frame
            frame_callback_count = [0]  # Usa lista per modificare in closure
            frame_callback_times = [None, None]  # [entry_time, exit_time]
            def frame_callback(frame):
                # #region agent log
                try:
                    _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_entry","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1690","message":"frame_callback ENTRY","data":{{"stream_id":"{stream_id}","frame_is_none":{frame is None},"queue_size":{frame_queue.qsize()},"queue_full":{frame_queue.full()},"queue_maxsize":{frame_queue.maxsize}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
                except Exception as e:
                    try:
                        self.log(f"[DEBUG LOG ERROR] {e}")
                    except:
                        pass
                # #endregion
                frame_callback_times[0] = time_module.time()
                try:
                    if not self.active_streams.get(stream_id, {}).get("running", False):
                        self.log(f"[DEBUG] {stream_id}: frame_callback chiamato ma stream non più attivo")
                        return False
                    
                    if frame is None:
                        self.log(f"[DEBUG] {stream_id}: frame_callback ricevuto frame None")
                        return True
                    
                    if frame.size == 0:
                        self.log(f"[DEBUG] {stream_id}: frame_callback ricevuto frame vuoto")
                        return True
                    
                    frame_callback_count[0] += 1
                    
                    # Aggiorna statistiche frame count per statistiche pagina
                    if 'frame_count' not in self.stats:
                        self.stats['frame_count'] = 0
                    self.stats['frame_count'] += 1
                    
                    queue_size_before_op = frame_queue.qsize()
                    queue_was_full_before = frame_queue.full()
                    
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_before_queue","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1698","message":"BEFORE queue operations","data":{{"stream_id":"{stream_id}","frame_num":{frame_callback_count[0]},"queue_size":{queue_size_before_op},"queue_full":{queue_was_full_before},"queue_maxsize":{frame_queue.maxsize}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    if frame_callback_count[0] == 1:
                        self.log(f"[DEBUG] {stream_id}: ✅ PRIMO FRAME ricevuto! dim: {frame.shape}, queue size prima: {frame_queue.qsize()}")
                    elif frame_callback_count[0] % 30 == 0:
                        self.log(f"[DEBUG] {stream_id}: frame_callback chiamato {frame_callback_count[0]} volte, dim: {frame.shape}, queue size: {frame_queue.qsize()}")
                    
                    # Aggiungi frame alla queue (rimuovi vecchi se piena)
                    frames_dropped = 0
                    while frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                            frames_dropped += 1
                            # #region agent log
                            try:
                                _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_drop","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1715","message":"Frame dropped from full queue","data":{{"stream_id":"{stream_id}","frames_dropped":{frames_dropped}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}}\n')
                            except Exception as e:
                                try:
                                    self.log(f"[DEBUG LOG ERROR] {e}")
                                except:
                                    pass
                            # #endregion
                        except queue.Empty:
                            break
                    
                    copy_start = time_module.time()
                    frame_copy = frame.copy()
                    copy_duration = time_module.time() - copy_start
                    
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_copy","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1725","message":"Frame copy timing","data":{{"stream_id":"{stream_id}","copy_duration_ms":{copy_duration*1000:.2f},"frame_shape":{list(frame.shape)}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"E"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    put_start = time_module.time()
                    frame_queue.put_nowait(frame_copy)
                    put_duration = time_module.time() - put_start
                    queue_size_after_op = frame_queue.qsize()
                    
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_after_queue","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1730","message":"AFTER queue operations","data":{{"stream_id":"{stream_id}","queue_size":{queue_size_after_op},"put_duration_ms":{put_duration*1000:.2f},"frames_dropped":{frames_dropped}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    if frame_callback_count[0] == 1:
                        self.log(f"[DEBUG] {stream_id}: Frame aggiunto alla queue, nuova size: {frame_queue.qsize()}")
                    
                except Exception as e:
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_error","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1735","message":"frame_callback EXCEPTION","data":{{"stream_id":"{stream_id}","error":{repr(str(e))}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"D"}}\n')
                    except Exception as ex:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {ex}")
                        except:
                            pass
                    # #endregion
                    self.log(f"[DEBUG] Errore in frame_callback per {stream_id}: {e}")
                    import traceback
                    self.log(traceback.format_exc())
                finally:
                    frame_callback_times[1] = time_module.time()
                    total_duration = frame_callback_times[1] - frame_callback_times[0] if frame_callback_times[0] else 0
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_fc_exit","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1745","message":"frame_callback EXIT","data":{{"stream_id":"{stream_id}","total_duration_ms":{total_duration*1000:.2f},"frame_num":{frame_callback_count[0]}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                return True
            
            # Funzione per ottenere parametri aggiornati in real-time
            def get_params_callback():
                """Callback per ottenere parametri aggiornati durante lo streaming."""
                params = self._get_realtime_params(stream_id)
                return {
                    "conf": params.get("conf", self.conf_var.get() if hasattr(self, 'conf_var') else 0.6),
                    "imgsz": params.get("imgsz", int(self.imgsz_var.get()) if hasattr(self, 'imgsz_var') else 640),
                    "enable_person_detection": params.get("enable_person_detection", self.enable_person_detection_var.get() if hasattr(self, 'enable_person_detection_var') else True),
                    "enable_vehicle_detection": params.get("enable_vehicle_detection", self.enable_vehicle_detection_var.get() if hasattr(self, 'enable_vehicle_detection_var') else False),
                }
            
            # Ottieni parametri iniziali
            initial_params = self._get_realtime_params(stream_id)
            
            self.log(f"[DEBUG] {stream_id}: Chiamata analyze_video con frame_callback={'presente' if frame_callback else 'NON presente'}")
            
            # #region agent log
            try:
                _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_analyze_start","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1820","message":"BEFORE analyze_video call","data":{{"stream_id":"{stream_id}","frame_callback_present":{frame_callback is not None},"frame_callback_count_before":{frame_callback_count[0]}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
            except Exception as e:
                try:
                    self.log(f"[DEBUG LOG ERROR] {e}")
                except:
                    pass
            # #endregion
            
            # Determina modello ottimale (solo se necessario)
            # Se tutte le funzioni sono disabilitate, non serve YOLO (modalità solo visualizzazione)
            model_name = self._get_optimal_yolo_model(initial_params)
            
            # Se model_name è None, analyze_video userà modalità solo visualizzazione
            if model_name is None:
                self.log(f"[DEBUG] {stream_id}: Modalità solo visualizzazione (YOLO non necessario - tutte le funzioni disabilitate)")
                # Assicurati che enable_yolo, enable_plates, enable_collision, enable_person_safety siano tutti False
                initial_params["enable_yolo"] = False
                initial_params["enable_plates"] = False
                initial_params["enable_collision"] = False
                initial_params["enable_person_safety"] = False
            
            # Configura OCR prima se necessario
            if initial_params.get("enable_plates", self.plates_var.get()):
                from modules.features.ocr_module import OCRModule
                languages = ['en', 'it'] if self.ocr_lang_var.get() == "en+it" else ['en']
                OCRModule.get_reader(languages=languages, quantize=self.ocr_quant_var.get())

            # Avvia streaming usando analyze_video (supporta RTSP)
            # NOTA: conf viene gestito tramite get_params_callback, non come parametro diretto
            # Se model_name è None, analyze_video userà modalità solo visualizzazione (non caricherà YOLO)
            # analyze_video determina automaticamente se serve YOLO in base a enable_plates, enable_collision, ecc.
            self.log(f"[DEBUG] {stream_id}: Chiamata analyze_video, model_name={model_name}, enable_yolo={initial_params.get('enable_yolo', False)}, url={url.split('@')[0]}@***")
            self.log(f"[DEBUG] {stream_id}: Parametri: enable_person_detection={initial_params.get('enable_person_detection', False)}, enable_vehicle_detection={initial_params.get('enable_vehicle_detection', False)}")
            self.log(f"[DEBUG] {stream_id}: stats_collector presente: {self.rtsp_stats_collector is not None}, frame_callback presente: {frame_callback is not None}")
            
            try:
                # Per URL RTSP, passa come stringa, non come Path
                # analyze_video riconosce automaticamente gli URL RTSP
                video_path_arg = url if url.startswith("rtsp://") else Path(url)
                self.log(f"[DEBUG] {stream_id}: Chiamando analyze_video ora...")
                result = analyze_video(
                    video_path=video_path_arg,  # analyze_video accetta anche URL RTSP come stringa
                    # Se model_name è None, modalità solo visualizzazione (YOLO non verrà caricato)
                    # analyze_video determina automaticamente se serve YOLO in base a enable_yolo, enable_plates, enable_collision, enable_person_safety
                    model_name=model_name if model_name else "yolo11n.pt",  # Se None, usa un modello di default (non verrà caricato se needs_yolo=False)
                    enable_yolo=initial_params.get("enable_yolo", False),  # Usa valore da initial_params (False se tutte le funzioni sono disabilitate)
                    enable_person_detection=initial_params.get("enable_person_detection", self.enable_person_detection_var.get() if hasattr(self, 'enable_person_detection_var') else True),
                    enable_vehicle_detection=initial_params.get("enable_vehicle_detection", self.enable_vehicle_detection_var.get() if hasattr(self, 'enable_vehicle_detection_var') else False),
                    enable_plates=initial_params.get("enable_plates", self.plates_var.get()),
                    enable_dashboard=False,
                    log_file=None,
                    enable_collision=initial_params.get("enable_collision", self.collision_var.get()),
                    enable_person_safety=initial_params.get("enable_person_safety", self.person_safety_var.get()),
                    enable_person_loitering=initial_params.get("enable_person_loitering", self.person_loiter_var.get()),
                    enable_person_fall=initial_params.get("enable_person_fall", self.person_fall_var.get()),
                    enable_person_vehicle_interaction=initial_params.get("enable_person_vehicle_interaction", self.person_vehicle_interaction_var.get() if hasattr(self, 'person_vehicle_interaction_var') else False),
                    enable_person_wall_writing=initial_params.get("enable_person_wall_writing", self.person_wall_writing_var.get() if hasattr(self, 'person_wall_writing_var') else False),
                    imgsz=self._get_optimized_imgsz(initial_params.get("imgsz", int(self.imgsz_var.get()) if hasattr(self, 'imgsz_var') else 640)),
                    frame_callback=frame_callback,
                    stop_flag=lambda: not self.active_streams.get(stream_id, {}).get("running", False),
                    stats_collector=self.rtsp_stats_collector,  # Usa collector condiviso per eventi RTSP
                    get_params_callback=get_params_callback  # Callback per parametri real-time (include conf, enable_person_detection, enable_vehicle_detection)
                )
                self.log(f"[DEBUG] {stream_id}: analyze_video restituito: {result}")
                # #region agent log
                try:
                    _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_analyze_end","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1877","message":"AFTER analyze_video call","data":{{"stream_id":"{stream_id}","frame_callback_count_after":{frame_callback_count[0]},"result":{repr(str(result)) if result else "None"}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
                except Exception as e:
                    try:
                        self.log(f"[DEBUG LOG ERROR] {e}")
                    except:
                        pass
                # #endregion
            except Exception as e:
                # #region agent log
                try:
                    _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_analyze_error","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:1882","message":"analyze_video EXCEPTION","data":{{"stream_id":"{stream_id}","error":{repr(str(e))},"frame_callback_count":{frame_callback_count[0]}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}}\n')
                except Exception as ex:
                    try:
                        self.log(f"[DEBUG LOG ERROR] {ex}")
                    except:
                        pass
                # #endregion
                self.log(f"[DEBUG] {stream_id}: ERRORE in analyze_video: {e}")
                import traceback
                self.log(traceback.format_exc())
                raise
            
            self.log(f"[DEBUG] {stream_id}: analyze_video completato, frame_callback chiamato {frame_callback_count[0]} volte totali")
        except Exception as e:
            self.log(f"❌ Errore stream {stream_id}: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            if stream_id in self.active_streams:
                self.active_streams[stream_id]["running"] = False
                self.log(f"[DEBUG] {stream_id}: Thread stream terminato")
    
    def load_cameras_config(self):
        """Carica configurazione telecamere da cameras_config.json e crea checkbox."""
        try:
            cameras_config_path = Path("config/cameras.json")
            if not cameras_config_path.exists():
                self.log("⚠️ File config/cameras.json non trovato")
                return
            
            with open(cameras_config_path, 'r', encoding='utf-8') as f:
                self.cameras_config = json.load(f)
            
            # Pulisci frame checkbox esistenti
            for widget in self.cameras_checkboxes_frame.winfo_children():
                widget.destroy()
            
            self.camera_vars = {}
            cameras = self.cameras_config.get("cameras", [])
            
            if not cameras:
                ttk.Label(self.cameras_checkboxes_frame, text="Nessuna telecamera configurata.\nEsegui tools/setup_cameras.py", 
                         foreground="#B0B0B0", background=self.colors["bg_panel"]).pack(pady=10)
                self.log("⚠️ File config/cameras.json valido ma vuoto.")
                return
            
            # Crea checkbox per ogni telecamera (tutte disattivate di default)
            for idx, camera in enumerate(cameras):
                camera_id = f"cam_{camera.get('channel', idx)}_{camera.get('stream_type', 'Main')}"
                # Forza False di default - le telecamere devono essere selezionate manualmente
                var = tk.BooleanVar(value=False)
                self.camera_vars[camera_id] = var
                
                # Frame per ogni telecamera (stile pannello)
                cam_frame = ttk.Frame(self.cameras_checkboxes_frame, style="Panel.TFrame")
                cam_frame.pack(fill="x", padx=5, pady=2)
                
                # Checkbox con stile
                cb = ttk.Checkbutton(cam_frame, text=camera.get("name", f"Camera {idx+1}"), 
                                    variable=var, style="TCheckbutton")
                cb.pack(side="left", padx=5)
                
                # Info telecamera
                info_text = f"Ch{camera.get('channel', '?')} - {camera.get('stream_type', 'Main')}"
                ttk.Label(cam_frame, text=info_text, font=("Arial", 8), foreground="#B0B0B0", style="Panel.TLabel").pack(side="left", padx=5)
                
                # Salva riferimento alla camera nel var per accesso rapido
                var.camera_data = camera
                var.camera_id = camera_id
            
            self.log(f"✅ Caricate {len(cameras)} telecamere da config/cameras.json")
            
            # Abilita pulsanti se ci sono telecamere
            if len(cameras) > 0:
                self.start_streaming_btn.config(state=tk.NORMAL)
            
        except Exception as e:
            self.log(f"❌ Errore caricamento telecamere: {e}")
            import traceback
            traceback.print_exc()
    
    def select_all_cameras(self):
        """Seleziona tutte le telecamere."""
        if not hasattr(self, 'camera_vars') or not self.camera_vars:
            return
        for var in self.camera_vars.values():
            var.set(True)
        self.log("✅ Tutte le telecamere selezionate")
    
    def deselect_all_cameras(self):
        """Deseleziona tutte le telecamere."""
        if not hasattr(self, 'camera_vars') or not self.camera_vars:
            return
        for var in self.camera_vars.values():
            var.set(False)
        self.log("✅ Tutte le telecamere deselezionate")
    
    def scan_network_cameras(self):
        """Avvia la scansione della rete per trovare telecamere NVR."""
        if messagebox.askyesno("Scansione Rete", "La scansione potrebbe richiedere alcuni minuti.\nVuoi procedere?"):
            self.update_status("Scansione telecamere in corso...")
            
            def scan_task():
                try:
                    from video_analysis import discover_cameras, save_cameras_config
                    
                    # Callback per aggiornare stato
                    def progress_cb(msg):
                        self.root.after(0, lambda: self.update_status(msg))
                        self.root.after(0, lambda: self.log(f"[SCAN] {msg}"))

                    self.log("Avvio scansione NVR...")
                    cameras = discover_cameras(max_channels=16, timeout=12.0, progress_callback=progress_cb)
                    
                    if cameras:
                        # Salva la nuova configurazione
                        save_cameras_config(cameras)
                        self.root.after(0, lambda: self.log(f"✅ Scansione completata: trovate {len(cameras)} telecamere."))
                        self.root.after(0, lambda: messagebox.showinfo("Scansione Completata", f"Trovate e salvate {len(cameras)} telecamere."))
                        # Ricarica la lista nel pannello
                        self.root.after(0, self.load_cameras_config)
                    else:
                        self.root.after(0, lambda: self.log("⚠️ Nessuna telecamera trovata durante la scansione."))
                        self.root.after(0, lambda: messagebox.showwarning("Scansione", "Nessuna telecamera trovata.\nVerifica connessione e credenziali RTSP."))
                    
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"❌ Errore scansione: {e}"))
                    self.root.after(0, lambda: messagebox.showerror("Errore Scansione", f"Si è verificato un errore:\n{e}"))
                finally:
                    self.root.after(0, lambda: self.update_status("Pronto"))

            # Esegui in thread separato
            threading.Thread(target=scan_task, daemon=True).start()

    def scan_network_cameras(self):
        """Avvia la scansione della rete per trovare telecamere NVR."""
        if messagebox.askyesno("Scansione Rete", "La scansione potrebbe richiedere alcuni minuti.\nVuoi procedere?"):
            self.log("Avvio scansione NVR...")
            
            def scan_task():
                try:
                    from video_analysis import discover_cameras, save_cameras_config
                    
                    # Callback per aggiornare stato
                    def progress_cb(msg):
                        self.root.after(0, lambda: self.log(f"[SCAN] {msg}"))

                    cameras = discover_cameras(max_channels=16, timeout=12.0, progress_callback=progress_cb)
                    
                    if cameras:
                        # Salva la nuova configurazione
                        save_cameras_config(cameras)
                        self.root.after(0, lambda: self.log(f"✅ Scansione completata: trovate {len(cameras)} telecamere."))
                        self.root.after(0, lambda: messagebox.showinfo("Scansione Completata", f"Trovate e salvate {len(cameras)} telecamere."))
                        # Ricarica la lista nel pannello
                        self.root.after(0, self.load_cameras_config)
                    else:
                        self.root.after(0, lambda: self.log("⚠️ Nessuna telecamera trovata durante la scansione."))
                        self.root.after(0, lambda: messagebox.showwarning("Scansione", "Nessuna telecamera trovata.\nVerifica connessione e credenziali RTSP."))
                    
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"❌ Errore scansione: {e}"))
                    self.root.after(0, lambda: messagebox.showerror("Errore Scansione", f"Si è verificato un errore:\n{e}"))

            # Esegui in thread separato
            threading.Thread(target=scan_task, daemon=True).start()

    def start_selected_cameras(self):
        """Avvia streaming per tutte le telecamere selezionate."""
        selected = []
        for camera_id, var in self.camera_vars.items():
            if var.get():
                camera = var.camera_data
                selected.append((camera_id, camera))
        
        if not selected:
            messagebox.showwarning("Attenzione", "Seleziona almeno una telecamera!")
            return
        
        # Verifica quali telecamere sono già attive (evita duplicati)
        active_urls = {stream_info.get("url") for stream_info in self.active_streams.values()}
        new_cameras = []
        skipped = 0
        
        for camera_id, camera in selected:
            url = camera.get("url")
            if url and url not in active_urls:
                new_cameras.append((camera_id, camera))
            elif url in active_urls:
                skipped += 1
        
        if skipped > 0:
            self.log(f"⚠️ {skipped} telecamera(e) già attiva/e, saltata/e")
        
        if not new_cameras:
            messagebox.showinfo("Info", "Tutte le telecamere selezionate sono già attive!")
            return
        
        self.log(f"▶️ Avvio streaming per {len(new_cameras)} telecamera(e)...")
        
        # Inizializza statistiche se non già inizializzate
        if self.stats.get('start_time') is None:
            import time
            self.stats['start_time'] = time.time()
            self.stats['status'] = "RUNNING"
        
        for camera_id, camera in new_cameras:
            url = camera.get("url")
            if url:
                self.log(f"[DEBUG] Avvio stream per camera {camera_id}: {url.split('@')[0]}@***")
                try:
                    self.add_camera_stream(url)
                    self.log(f"[DEBUG] ✅ Stream {camera_id} aggiunto con successo")
                except Exception as e:
                    self.log(f"❌ Errore aggiunta stream {camera_id}: {e}")
                    import traceback
                    self.log(traceback.format_exc())
                # Piccolo delay per evitare sovraccarico
                import time
                time.sleep(0.2)
            else:
                self.log(f"⚠️ Camera {camera_id} non ha URL valido")
        
        self.log(f"✅ Streaming avviato per {len(new_cameras)} telecamera(e)")
    
    def stop_all_cameras(self):
        """Ferma tutti gli stream attivi."""
        if not self.active_streams:
            messagebox.showinfo("Info", "Nessuno stream attivo")
            return
        
        count = len(self.active_streams)
        for stream_id in list(self.active_streams.keys()):
            self.remove_camera_stream(stream_id)
        
        self.log(f"⏹️ Fermati {count} stream")
        messagebox.showinfo("Info", f"Fermati {count} stream")
        
        # Disabilita pulsanti
        self.stop_all_streams_btn.config(state=tk.DISABLED)
        self.remove_camera_btn.config(state=tk.DISABLED)
    
    def remove_camera_stream(self, stream_id):
        """Rimuove uno stream specifico."""
        if stream_id in self.active_streams:
            stream_info = self.active_streams[stream_id]
            stream_info["running"] = False
            if "thread" in stream_info:
                # Il thread si fermerà automaticamente quando running=False
                pass
            
            # Rimuovi dalla lista
            if hasattr(self, 'cameras_listbox'):
                items = self.cameras_listbox.get(0, tk.END)
                for i, item in enumerate(items):
                    if stream_id in item:
                        self.cameras_listbox.delete(i)
                        break
            
            del self.active_streams[stream_id]
            self._update_video_layout()
            self.log(f"⏹️ Stream {stream_id} fermato")
            
            # Disabilita pulsanti se non ci sono più stream
            if len(self.active_streams) == 0:
                self.stop_all_streams_btn.config(state=tk.DISABLED)
                self.remove_camera_btn.config(state=tk.DISABLED)
    
    def remove_selected_camera(self):
        """Rimuove la telecamera selezionata."""
        if not hasattr(self, 'cameras_listbox'):
            return
        
        selection = self.cameras_listbox.curselection()
        if not selection:
            messagebox.showwarning("Attenzione", "Seleziona una telecamera da rimuovere.")
            return
        
        index = selection[0]
        item_text = self.cameras_listbox.get(index)
        
        # Estrai stream_id dal testo (formato: "stream_X: url@***")
        stream_id = None
        for sid in self.active_streams.keys():
            if sid in item_text:
                stream_id = sid
                break
        
        if stream_id is None:
            messagebox.showerror("Errore", "Impossibile identificare lo stream da rimuovere.")
            return
        
        # Ferma e rimuovi stream
        self.remove_camera_stream(stream_id)
    
    def _update_video_layout(self):
        """Aggiorna layout video per supportare più telecamere."""
        num_streams = len(self.active_streams)
        
        # Pulisci frame griglia
        if hasattr(self, 'video_grid_frame'):
            for widget in self.video_grid_frame.winfo_children():
                widget.destroy()
        else:
            return
        
        if num_streams == 0:
            # Nessuno stream, mostra canvas principale
            self.video_canvas = tk.Canvas(self.video_grid_frame, bg="black", width=800, height=600,
                                         highlightthickness=2, highlightbackground="#34495e")
            self.video_canvas.pack(fill="both", expand=True)
            self.video_label = tk.Label(
                self.video_canvas,
                text="🎥 Video apparirà qui durante l'analisi\n\nSeleziona un video o avvia streaming RTSP",
                fg="white", bg="black", font=("Arial", 16, "bold"), justify=tk.CENTER
            )
            self.video_canvas.create_window(400, 300, window=self.video_label)
        elif num_streams == 1:
            # Un solo stream, usa canvas principale
            self.video_canvas = tk.Canvas(self.video_grid_frame, bg="black", width=800, height=600,
                                         highlightthickness=2, highlightbackground="#34495e")
            self.video_canvas.pack(fill="both", expand=True)
            # Avvia aggiornamento per questo stream
            stream_id = list(self.active_streams.keys())[0]
            # IMPORTANTE: assicurati che il thread display non sia già attivo
            if stream_id in self.active_streams and "display_thread" in self.active_streams[stream_id]:
                if self.active_streams[stream_id]["display_thread"].is_alive():
                    # Thread già attivo, non riavviarlo
                    self.log(f"[DEBUG] Thread display già attivo per {stream_id}, skip")
                else:
                    # Thread morto, riavvialo
                    self._start_stream_display(stream_id, self.video_canvas)
            else:
                # Nessun thread, avvialo
                self._start_stream_display(stream_id, self.video_canvas)
        else:
            # Più stream, crea griglia
            import math
            cols = math.ceil(math.sqrt(num_streams))
            rows = math.ceil(num_streams / cols)
            
            for i, stream_id in enumerate(self.active_streams.keys()):
                row = i // cols
                col = i % cols
                
                # Crea canvas con dimensioni minime valide
                # Usa dimensioni più grandi per migliorare la visibilità
                canvas = tk.Canvas(self.video_grid_frame, bg="black", 
                                 highlightthickness=1, highlightbackground="#34495e",
                                 width=600, height=450)  # Dimensioni più grandi per migliore visibilità
                canvas.grid(row=row, column=col, sticky=(tk.W, tk.E, tk.N, tk.S), padx=2, pady=2)
                
                # Label iniziale con ID stream (verrà rimossa al primo frame)
                label = tk.Label(canvas, text=f"Stream {stream_id}\nAttesa frame...", 
                               fg="white", bg="black", font=("Arial", 12, "bold"), justify=tk.CENTER)
                canvas.create_window(300, 225, window=label, anchor=tk.CENTER)  # Centrato nelle nuove dimensioni
                canvas.initial_label = label  # Salva riferimento per rimuoverlo dopo
                
                # Forza aggiornamento del canvas per assicurarsi che sia visibile
                canvas.update_idletasks()
                
                # IMPORTANTE: assicurati che il thread display non sia già attivo per questo stream
                # Se è già attivo, fermalo prima di riavviarlo con il nuovo canvas
                if stream_id in self.active_streams and "display_thread" in self.active_streams[stream_id]:
                    old_thread = self.active_streams[stream_id]["display_thread"]
                    if old_thread.is_alive():
                        # Thread già attivo, fermalo prima di riavviarlo
                        self.log(f"[DEBUG] Fermando thread display esistente per {stream_id} prima di riavviarlo")
                        # Il thread si fermerà quando running=False, ma qui dobbiamo solo riavviarlo
                        pass
                
                # Avvia aggiornamento per questo stream
                self._start_stream_display(stream_id, canvas)
            
            # Configura grid - IMPORTANTE: configura row e column weights per permettere il ridimensionamento
            for i in range(rows):
                self.video_grid_frame.rowconfigure(i, weight=1, minsize=300)
            for i in range(cols):
                self.video_grid_frame.columnconfigure(i, weight=1, minsize=400)
            
            # Forza aggiornamento del layout per assicurarsi che i canvas siano visibili
            self.video_grid_frame.update_idletasks()
    
    def _start_stream_display(self, stream_id, canvas):
        """Avvia thread per aggiornare display di uno stream (ottimizzato)."""
        import os
        _log_path = r"c:\Users\falba\OneDrive - ABIVET-UPVET\Desktop\Test progetti Yolo\.cursor\debug.log"
        _log_dir = os.path.dirname(_log_path)
        if not os.path.exists(_log_dir):
            os.makedirs(_log_dir, exist_ok=True)
        def _write_debug_log(data_str):
            try:
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(data_str)
            except Exception as e:
                try:
                    self.log(f"[DEBUG LOG ERROR] {e}")
                except:
                    pass
        # IMPORTANTE: se c'è già un thread attivo, fermalo prima di crearne uno nuovo
        # Questo evita conflitti quando il layout viene aggiornato
        if stream_id in self.active_streams and "display_thread" in self.active_streams[stream_id]:
            old_thread = self.active_streams[stream_id]["display_thread"]
            if old_thread.is_alive():
                self.log(f"[DEBUG] Thread display già attivo per {stream_id}, fermo il vecchio thread")
                # Non fermare il thread qui, ma assicurati che il nuovo thread usi il nuovo canvas
                # Il vecchio thread continuerà ma userà il vecchio canvas (che verrà distrutto)
                # Il nuovo thread userà il nuovo canvas
        
        def update_display():
            import time
            import time as time_module
            frame_count = 0
            no_frame_count = 0
            self.log(f"[DEBUG] Thread display avviato per {stream_id}")
            last_consumption_time = time_module.time()
            while self.active_streams.get(stream_id, {}).get("running", False):
                loop_start = time_module.time()
                try:
                    if stream_id not in self.active_streams:
                        self.log(f"[DEBUG] {stream_id}: stream_id non più in active_streams")
                        break
                    frame_queue = self.active_streams[stream_id].get("frame_queue")
                    if frame_queue is None:
                        if no_frame_count == 0 or no_frame_count % 100 == 0:
                            self.log(f"[DEBUG] {stream_id}: frame_queue è None, attesa...")
                        no_frame_count += 1
                        time.sleep(0.1)
                        continue
                    
                    # Prendi solo l'ultimo frame disponibile (scarta i vecchi)
                    latest_frame = None
                    queue_size_before = frame_queue.qsize()
                    frames_consumed = 0
                    
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_disp_before_get","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:2283","message":"Display thread BEFORE get","data":{{"stream_id":"{stream_id}","queue_size":{queue_size_before},"queue_empty":{frame_queue.empty()}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    get_start = time_module.time()
                    try:
                        while True:
                            latest_frame = frame_queue.get_nowait()
                            frames_consumed += 1
                    except queue.Empty:
                        pass
                    get_duration = time_module.time() - get_start
                    
                    # #region agent log
                    try:
                        time_since_last_cons = time_module.time() - last_consumption_time if last_consumption_time else 0
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_disp_after_get","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:2297","message":"Display thread AFTER get","data":{{"stream_id":"{stream_id}","frames_consumed":{frames_consumed},"get_duration_ms":{get_duration*1000:.2f},"time_since_last_cons_ms":{time_since_last_cons*1000:.2f},"frame_received":{latest_frame is not None}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    if latest_frame is not None:
                        frame_count += 1
                        no_frame_count = 0  # Reset contatore
                        last_consumption_time = time_module.time()
                        if frame_count == 1:
                            self.log(f"[DEBUG] {stream_id}: ✅ PRIMO FRAME visualizzato! dim: {latest_frame.shape}, queue size era: {queue_size_before}")
                        elif frame_count % 30 == 0:
                            self.log(f"[DEBUG] {stream_id}: frame {frame_count} visualizzato, dim: {latest_frame.shape}")
                        # Aggiorna canvas
                        self.root.after(0, lambda f=latest_frame.copy(), c=canvas: self._display_frame_on_canvas(f, c))
                    else:
                        # Nessun frame disponibile
                        no_frame_count += 1
                        if no_frame_count == 50:  # Dopo 5 secondi senza frame
                            self.log(f"[DEBUG] {stream_id}: ⚠️ Nessun frame ricevuto da {no_frame_count * 0.1:.1f} secondi, queue size: {queue_size_before}")
                        time.sleep(0.1)
                        continue
                    
                    loop_duration = time_module.time() - loop_start
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_disp_loop","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:2323","message":"Display thread loop timing","data":{{"stream_id":"{stream_id}","loop_duration_ms":{loop_duration*1000:.2f},"frame_count":{frame_count}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}}\n')
                    except Exception as e:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {e}")
                        except:
                            pass
                    # #endregion
                    
                    # Ottimizza FPS display in base al numero di stream attivi
                    active_streams_count = len([s for s in self.active_streams.values() if s.get("running", False)])
                    if active_streams_count >= 3:
                        time.sleep(0.1)  # ~10 FPS quando ci sono 3+ stream (riduce carico)
                    elif active_streams_count == 2:
                        time.sleep(0.05)  # ~20 FPS con 2 stream
                    else:
                        time.sleep(0.033)  # ~30 FPS con 1 stream
                except Exception as e:
                    # #region agent log
                    try:
                        _write_debug_log(f'{{"id":"log_{int(time_module.time()*1000)}_disp_error","timestamp":{int(time_module.time()*1000)},"location":"main_panel.py:2332","message":"Display thread EXCEPTION","data":{{"stream_id":"{stream_id}","error":{repr(str(e))}}},"sessionId":"debug-session","runId":"run1","hypothesisId":"D"}}\n')
                    except Exception as ex:
                        try:
                            self.log(f"[DEBUG LOG ERROR] {ex}")
                        except:
                            pass
                    # #endregion
                    self.log(f"[DEBUG] Errore in update_display per {stream_id}: {e}")
                    import traceback
                    self.log(traceback.format_exc())
                    time.sleep(0.1)
            self.log(f"[DEBUG] Thread display terminato per {stream_id}, totali frame visualizzati: {frame_count}")
        
        display_thread = threading.Thread(target=update_display, daemon=True)
        display_thread.start()
        # Salva riferimento al thread
        if stream_id in self.active_streams:
            self.active_streams[stream_id]["display_thread"] = display_thread
    
    def _display_frame_on_canvas(self, frame, canvas):
        """Mostra un frame su un canvas (funzione unificata ottimizzata)."""
        try:
            if frame is None or frame.size == 0:
                return
            
            # Rimuovi label iniziale al primo frame
            if hasattr(canvas, 'initial_label'):
                canvas.delete("all")
                delattr(canvas, 'initial_label')
            elif canvas == self.video_canvas and not self.video_started:
                canvas.delete("all")
                self.video_started = True
            
            # Converti BGR a RGB (ottimizzato - evita conversione se già RGB)
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:
                frame_rgb = frame
            
            # Converti a PIL Image
            pil_image = Image.fromarray(frame_rgb)
            
            # Ottieni dimensioni canvas - forza aggiornamento
            canvas.update_idletasks()
            canvas_width = canvas.winfo_width()
            canvas_height = canvas.winfo_height()
            
            # Se il canvas non ha ancora dimensioni valide, usa dimensioni di default
            if canvas_width <= 1 or canvas_height <= 1:
                # Prova a ottenere dimensioni dal parent o usa dimensioni di default
                try:
                    parent = canvas.master
                    if hasattr(parent, 'winfo_width'):
                        parent_w = parent.winfo_width()
                        parent_h = parent.winfo_height()
                        # Se è una griglia con più telecamere, calcola dimensioni per cella
                        if parent_w > 100 and parent_h > 100:
                            # Stima dimensioni per cella (assumendo griglia 2x2 o simile)
                            canvas_width = max(parent_w // 2 - 20, 400)
                            canvas_height = max(parent_h // 2 - 20, 300)
                        else:
                            canvas_width = max(parent_w - 20, 400)
                            canvas_height = max(parent_h - 20, 300)
                    else:
                        # Usa dimensioni di default basate sul tipo di canvas
                        canvas_width = 600  # Dimensioni più grandi per griglia
                        canvas_height = 450
                except:
                    canvas_width = 600
                    canvas_height = 450
            
            # Ridimensiona solo se necessario (ottimizzazione)
            img_w, img_h = pil_image.size
            if img_w > canvas_width or img_h > canvas_height:
                # Calcola scale mantenendo aspect ratio
                scale = min(canvas_width / img_w, canvas_height / img_h) * 0.95
                new_size = (int(img_w * scale), int(img_h * scale))
                if new_size[0] > 0 and new_size[1] > 0:
                    pil_image = pil_image.resize(new_size, Image.Resampling.LANCZOS)
            elif img_w < canvas_width and img_h < canvas_height:
                # Se l'immagine è più piccola, non ridimensionare (mantieni qualità)
                pass
            
            # Converti a PhotoImage
            photo = ImageTk.PhotoImage(image=pil_image)
            
            # Aggiorna canvas (un solo delete invece di multipli)
            canvas.delete("all")
            x = canvas_width // 2
            y = canvas_height // 2
            canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
            
            # Mantieni riferimento (evita garbage collection)
            canvas.image = photo
            if canvas == self.video_canvas:
                self.current_video_image = photo
        except Exception as e:
            # Log errore invece di ignorare silenziosamente
            print(f"[DEBUG] Errore in _display_frame_on_canvas: {e}")
            import traceback
            traceback.print_exc()
    
    def on_closing(self):
        """Gestisce chiusura finestra."""
        if self.processing_process:
            if messagebox.askokcancel("Uscita", "Analisi in corso. Terminare?"):
                self.running = False
                if self.processing_process:
                    self.processing_process.terminate()
                self.root.destroy()
        else:
            self.running = False
            self.root.destroy()


def main():
    root = tk.Tk()
    app = CompleteControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()

