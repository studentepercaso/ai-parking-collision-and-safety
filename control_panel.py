"""
Pannello di controllo completo per analisi video con collision detection.
Include dashboard integrata, controlli interattivi e visualizzazione in tempo reale.
"""

# Importa il pannello completo
from control_panel_complete import CompleteControlPanel, main

if __name__ == "__main__":
    import tkinter as tk
    root = tk.Tk()
    app = CompleteControlPanel(root)
    root.mainloop()


