"""
Test istanziazione pannello (senza avviare GUI completa).
"""

import sys
import tkinter as tk

def test_panel_instantiation():
    """Test che il pannello possa essere istanziato."""
    print("=" * 60)
    print("TEST: Istanziazione Pannello")
    print("=" * 60)
    
    try:
        # Crea root Tkinter (non mostrato)
        root = tk.Tk()
        root.withdraw()  # Nascondi finestra
        
        # Importa e istanzia pannello
        from control_panel_complete import CompleteControlPanel
        panel = CompleteControlPanel(root)
        
        print("✅ Pannello istanziato correttamente")
        
        # Verifica attributi essenziali
        essential_attrs = [
            'video_path', 'stats', 'collision_config', 
            'video_frame_queue', 'stats_queue', 'active_streams',
            'realtime_params', 'params_lock'
        ]
        
        missing = []
        for attr in essential_attrs:
            if not hasattr(panel, attr):
                missing.append(attr)
        
        if missing:
            print(f"⚠️  Attributi mancanti: {missing}")
        else:
            print("✅ Attributi essenziali presenti")
        
        # Verifica che le code siano inizializzate
        if hasattr(panel, 'video_frame_queue') and panel.video_frame_queue is not None:
            print("✅ video_frame_queue inizializzata")
        else:
            print("❌ video_frame_queue non inizializzata")
        
        if hasattr(panel, 'stats_queue') and panel.stats_queue is not None:
            print("✅ stats_queue inizializzata")
        else:
            print("❌ stats_queue non inizializzata")
        
        # Verifica lock
        if hasattr(panel, 'params_lock') and panel.params_lock is not None:
            print("✅ params_lock inizializzato")
        else:
            print("❌ params_lock non inizializzato")
        
        # Chiudi root
        root.destroy()
        
        print("\n✅ TEST COMPLETATO CON SUCCESSO")
        return True
        
    except Exception as e:
        print(f"❌ ERRORE durante istanziazione: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_panel_instantiation()
    sys.exit(0 if success else 1)



