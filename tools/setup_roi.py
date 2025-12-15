"""
Script per definire visivamente ROI parcheggio e maschere ostacoli.
Interfaccia con pulsanti visivi (Tkinter + OpenCV per disegno).
"""

import cv2
import numpy as np
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import argparse
import base64
import io
from PIL import Image

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
except ImportError:
    print("Errore: Tkinter non disponibile. Installa tkinter.")
    tk = None


ZONES_CONFIG_FILE = Path("zones_config.json")
MASKS_DIR = Path("obstacle_masks")
MASKS_DIR.mkdir(exist_ok=True)


def load_zones_config() -> dict:
    """Carica configurazione zone esistenti."""
    if ZONES_CONFIG_FILE.exists():
        with open(ZONES_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_zones_config(config: dict) -> None:
    """Salva configurazione zone."""
    ZONES_CONFIG_FILE.parent.mkdir(exist_ok=True)
    with open(ZONES_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def mask_to_base64(mask: np.ndarray) -> str:
    """Converte maschera numpy in stringa base64 per JSON."""
    mask_uint8 = (mask * 255).astype(np.uint8)
    pil_img = Image.fromarray(mask_uint8)
    buffer = io.BytesIO()
    pil_img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def base64_to_mask(data: str, shape: Tuple[int, int]) -> np.ndarray:
    """Converte stringa base64 in maschera numpy."""
    img_data = base64.b64decode(data)
    pil_img = Image.open(io.BytesIO(img_data))
    mask = np.array(pil_img.convert("L")) > 127
    # Ridimensiona se necessario
    if mask.shape != shape:
        mask = cv2.resize(mask.astype(np.uint8), (shape[1], shape[0])).astype(bool)
    return mask


class ZoneSelectorGUI:
    """Interfaccia grafica per definire ROI parcheggio e maschere ostacoli."""
    
    def __init__(self, image_path: str, camera_id: str):
        if tk is None:
            raise ImportError("Tkinter non disponibile")
        
        self.image_bgr = cv2.imread(image_path)
        if self.image_bgr is None:
            raise ValueError(f"Impossibile caricare immagine: {image_path}")
        
        self.image_rgb = cv2.cvtColor(self.image_bgr, cv2.COLOR_BGR2RGB)
        self.h, self.w = self.image_bgr.shape[:2]
        self.camera_id = camera_id
        
        # Stato
        self.mode = "parking_roi"  # "parking_roi" o "obstacle_mask"
        self.parking_points: List[Tuple[int, int]] = []
        self.current_obstacle_name: Optional[str] = None
        self.current_mask: Optional[np.ndarray] = None
        self.obstacles: Dict[str, np.ndarray] = {}  # nome -> maschera
        
        # Setup Tkinter
        self.root = tk.Tk()
        self.root.title(f"Setup Zone - {camera_id}")
        self.root.geometry("1200x800")
        
        # Frame sinistro: immagine con canvas
        left_frame = tk.Frame(self.root)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        self.canvas = tk.Canvas(left_frame, bg="gray")
        self.canvas.pack(fill="both", expand=True)
        
        # Carica immagine su canvas
        self._update_canvas()
        
        # Bind mouse
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        
        # Frame destro: controlli
        right_frame = tk.Frame(self.root, width=300)
        right_frame.pack(side="right", fill="y", padx=10, pady=10)
        right_frame.pack_propagate(False)
        
        self._create_controls(right_frame)
        
        # Variabili disegno
        self.drawing = False
        self.last_x = 0
        self.last_y = 0
        
    def _create_controls(self, parent: tk.Frame):
        """Crea pannello controlli con pulsanti."""
        tk.Label(parent, text="Setup Zone", font=("Arial", 14, "bold")).pack(pady=10)
        
        # Modalità
        mode_frame = tk.LabelFrame(parent, text="Modalità", padx=10, pady=10)
        mode_frame.pack(fill="x", pady=5)
        
        self.mode_var = tk.StringVar(value="parking_roi")
        tk.Radiobutton(
            mode_frame, text="ROI Parcheggio (Poligono)", 
            variable=self.mode_var, value="parking_roi",
            command=self._on_mode_change
        ).pack(anchor="w")
        tk.Radiobutton(
            mode_frame, text="Maschera Ostacolo (Disegno)", 
            variable=self.mode_var, value="obstacle_mask",
            command=self._on_mode_change
        ).pack(anchor="w")
        
        # Controlli ROI Parcheggio
        self.parking_frame = tk.LabelFrame(parent, text="ROI Parcheggio", padx=10, pady=10)
        self.parking_frame.pack(fill="x", pady=5)
        
        tk.Button(
            self.parking_frame, text="Reset ROI", command=self._reset_parking,
            bg="#FF9800", fg="white", width=20
        ).pack(pady=2)
        tk.Label(
            self.parking_frame, text="Clicca per aggiungere vertici",
            font=("Arial", 9), fg="gray"
        ).pack()
        
        # Controlli Maschera Ostacolo
        self.obstacle_frame = tk.LabelFrame(parent, text="Maschera Ostacolo", padx=10, pady=10)
        self.obstacle_frame.pack(fill="x", pady=5)
        
        tk.Button(
            self.obstacle_frame, text="Nuova Maschera", command=self._new_obstacle,
            bg="#2196F3", fg="white", width=20
        ).pack(pady=2)
        tk.Button(
            self.obstacle_frame, text="Reset Corrente", command=self._reset_current_mask,
            bg="#FF9800", fg="white", width=20
        ).pack(pady=2)
        tk.Label(
            self.obstacle_frame, text="Tieni premuto e disegna",
            font=("Arial", 9), fg="gray"
        ).pack()
        
        self.obstacle_list = tk.Listbox(self.obstacle_frame, height=5)
        self.obstacle_list.pack(fill="x", pady=5)
        tk.Button(
            self.obstacle_frame, text="Elimina Selezionato", command=self._delete_obstacle,
            bg="#F44336", fg="white", width=20
        ).pack(pady=2)
        
        # Salvataggio
        save_frame = tk.Frame(parent)
        save_frame.pack(fill="x", pady=20)
        
        tk.Button(
            save_frame, text="💾 SALVA TUTTO", command=self._save_all,
            bg="#4CAF50", fg="white", font=("Arial", 12, "bold"), width=25, height=2
        ).pack(pady=5)
        tk.Button(
            save_frame, text="❌ ANNULLA", command=self._cancel,
            bg="#F44336", fg="white", width=25, height=2
        ).pack(pady=5)
        
        self._on_mode_change()
    
    def _on_mode_change(self):
        """Cambia modalità e mostra/nascondi controlli."""
        self.mode = self.mode_var.get()
        if self.mode == "parking_roi":
            self.parking_frame.pack(fill="x", pady=5)
            self.obstacle_frame.pack_forget()
        else:
            self.parking_frame.pack_forget()
            self.obstacle_frame.pack(fill="x", pady=5)
        self._update_canvas()
    
    def _on_click(self, event):
        """Gestisce click mouse."""
        x = int(self.canvas.canvasx(event.x))
        y = int(self.canvas.canvasy(event.y))
        
        # Scala coordinate se canvas è ridimensionato
        scale_x = self.w / self.canvas.winfo_width() if self.canvas.winfo_width() > 0 else 1.0
        scale_y = self.h / self.canvas.winfo_height() if self.canvas.winfo_height() > 0 else 1.0
        x = int(x * scale_x)
        y = int(y * scale_y)
        x = max(0, min(x, self.w - 1))
        y = max(0, min(y, self.h - 1))
        
        if self.mode == "parking_roi":
            self.parking_points.append((x, y))
            self._update_canvas()
        else:  # obstacle_mask
            if self.current_mask is None:
                messagebox.showwarning("Attenzione", "Crea prima una nuova maschera ostacolo!")
                return
            self.drawing = True
            self.last_x, self.last_y = x, y
            self._draw_on_mask(x, y, x, y)
    
    def _on_drag(self, event):
        """Gestisce trascinamento mouse (per disegno maschera)."""
        if not self.drawing or self.mode != "obstacle_mask" or self.current_mask is None:
            return
        
        x = int(self.canvas.canvasx(event.x))
        y = int(self.canvas.canvasy(event.y))
        scale_x = self.w / self.canvas.winfo_width() if self.canvas.winfo_width() > 0 else 1.0
        scale_y = self.h / self.canvas.winfo_height() if self.canvas.winfo_height() > 0 else 1.0
        x = int(x * scale_x)
        y = int(y * scale_y)
        x = max(0, min(x, self.w - 1))
        y = max(0, min(y, self.h - 1))
        
        self._draw_on_mask(self.last_x, self.last_y, x, y)
        self.last_x, self.last_y = x, y
        self._update_canvas()
    
    def _on_release(self, event):
        """Gestisce rilascio mouse."""
        self.drawing = False
    
    def _draw_on_mask(self, x1: int, y1: int, x2: int, y2: int):
        """Disegna sulla maschera corrente."""
        if self.current_mask is None:
            return
        cv2.line(self.current_mask, (x1, y1), (x2, y2), True, thickness=5)
    
    def _update_canvas(self):
        """Aggiorna canvas con immagine + disegni."""
        img = self.image_rgb.copy()
        
        # Disegna ROI parcheggio
        if len(self.parking_points) >= 2:
            pts = np.array(self.parking_points, np.int32)
            cv2.polylines(img, [pts], False, (0, 255, 0), 2)
            if len(self.parking_points) >= 3:
                overlay = img.copy()
                cv2.fillPoly(overlay, [pts], (0, 255, 0))
                img = cv2.addWeighted(overlay, 0.3, img, 0.7, 0)
            for i, (x, y) in enumerate(self.parking_points):
                cv2.circle(img, (x, y), 5, (0, 255, 0), -1)
                cv2.putText(img, str(i+1), (x+10, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Disegna maschere ostacoli
        for name, mask in self.obstacles.items():
            color = (255, 0, 0) if name == self.current_obstacle_name else (255, 165, 0)
            mask_rgb = np.zeros((self.h, self.w, 3), dtype=np.uint8)
            mask_rgb[mask] = color
            img = cv2.addWeighted(img, 0.7, mask_rgb, 0.3, 0)
        
        # Disegna maschera corrente
        if self.current_mask is not None:
            mask_rgb = np.zeros((self.h, self.w, 3), dtype=np.uint8)
            mask_rgb[self.current_mask] = (255, 0, 0)
            img = cv2.addWeighted(img, 0.7, mask_rgb, 0.3, 0)
        
        # Converti per Tkinter
        pil_img = Image.fromarray(img)
        # Ridimensiona per fit canvas
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w > 1 and canvas_h > 1:
            scale = min(canvas_w / self.w, canvas_h / self.h, 1.0)
            new_w = int(self.w * scale)
            new_h = int(self.h * scale)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        from PIL import ImageTk
        self.photo = ImageTk.PhotoImage(image=pil_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
    
    def _reset_parking(self):
        """Reset ROI parcheggio."""
        self.parking_points = []
        self._update_canvas()
    
    def _new_obstacle(self):
        """Crea nuova maschera ostacolo."""
        name = simpledialog.askstring("Nuova Maschera", "Nome ostacolo (es. 'palo_1', 'muro'):")
        if not name:
            return
        if name in self.obstacles:
            if not messagebox.askyesno("Conferma", f"'{name}' esiste già. Sostituire?"):
                return
        self.current_obstacle_name = name
        self.current_mask = np.zeros((self.h, self.w), dtype=bool)
        self._update_obstacle_list()
        self._update_canvas()
    
    def _reset_current_mask(self):
        """Reset maschera corrente."""
        if self.current_mask is not None:
            self.current_mask = np.zeros((self.h, self.w), dtype=bool)
            self._update_canvas()
    
    def _delete_obstacle(self):
        """Elimina ostacolo selezionato."""
        selection = self.obstacle_list.curselection()
        if not selection:
            return
        name = self.obstacle_list.get(selection[0])
        del self.obstacles[name]
        if name == self.current_obstacle_name:
            self.current_obstacle_name = None
            self.current_mask = None
        self._update_obstacle_list()
        self._update_canvas()
    
    def _update_obstacle_list(self):
        """Aggiorna lista ostacoli."""
        self.obstacle_list.delete(0, tk.END)
        for name in self.obstacles.keys():
            self.obstacle_list.insert(tk.END, name)
        if self.current_obstacle_name and self.current_obstacle_name not in self.obstacles:
            self.obstacle_list.insert(tk.END, f"{self.current_obstacle_name} (in corso)")
    
    def _save_all(self):
        """Salva tutto in zones_config.json."""
        if len(self.parking_points) < 3:
            messagebox.showerror("Errore", "Aggiungi almeno 3 punti per il ROI parcheggio!")
            return
        
        # Salva maschera corrente se c'è
        if self.current_mask is not None and self.current_obstacle_name:
            self.obstacles[self.current_obstacle_name] = self.current_mask.copy()
        
        config = load_zones_config()
        config[self.camera_id] = {
            "parking_roi": [[int(x), int(y)] for x, y in self.parking_points],
            "obstacles": {}
        }
        
        # Salva maschere come base64
        for name, mask in self.obstacles.items():
            config[self.camera_id]["obstacles"][name] = {
                "mask_base64": mask_to_base64(mask),
                "shape": [int(self.h), int(self.w)]
            }
        
        save_zones_config(config)
        messagebox.showinfo("Successo", f"Configurazione salvata per '{self.camera_id}'!")
        self.root.quit()
    
    def _cancel(self):
        """Annulla e chiudi."""
        if messagebox.askyesno("Conferma", "Annullare e uscire senza salvare?"):
            self.root.quit()
    
    def run(self) -> bool:
        """Avvia interfaccia."""
        self.root.mainloop()
        return True


def setup_zones_from_image(image_path: str, camera_id: str) -> None:
    """Definisce zone da un'immagine."""
    if tk is None:
        print("Errore: Tkinter non disponibile. Usa --image con OpenCV.")
        return
    
    selector = ZoneSelectorGUI(image_path, camera_id)
    selector.run()


def setup_zones_from_video(video_path: str, camera_id: str, frame_number: int = 0) -> None:
    """Estrae un frame da un video e definisce zone da quello."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Errore: impossibile aprire video {video_path}")
        return
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print(f"Errore: impossibile leggere frame {frame_number}")
        return
    
    temp_image = Path("temp_roi_frame.jpg")
    cv2.imwrite(str(temp_image), frame)
    
    try:
        setup_zones_from_image(str(temp_image), camera_id)
    finally:
        if temp_image.exists():
            temp_image.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup ROI parcheggio e maschere ostacoli")
    parser.add_argument("--image", type=str, help="Percorso immagine")
    parser.add_argument("--video", type=str, help="Percorso video")
    parser.add_argument("--frame", type=int, default=0, help="Numero frame da usare (se --video)")
    parser.add_argument("--camera-id", type=str, required=True, help="ID telecamera")
    
    args = parser.parse_args()
    
    if args.image:
        setup_zones_from_image(args.image, args.camera_id)
    elif args.video:
        setup_zones_from_video(args.video, args.camera_id, args.frame)
    else:
        print("Errore: specifica --image o --video")
        parser.print_help()
