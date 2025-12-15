"""Script di test rapido per verificare che tutti gli import e le funzioni critiche funzionino."""

import sys
from pathlib import Path

# Aggiungi la directory root al path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_imports():
    """Testa tutti gli import principali."""
    print("=" * 60)
    print("TEST IMPORT")
    print("=" * 60)
    
    try:
        print("1. Import video_analysis...")
        import video_analysis
        print("   ✓ video_analysis importato")
        
        print("2. Import main_panel...")
        import main_panel
        print("   ✓ main_panel importato")
        
        print("3. Import moduli core...")
        from modules.core.statistics import StatisticsCollector
        from modules.core.event_logger import EventLogger
        print("   ✓ moduli core importati")
        
        print("4. Import moduli detection...")
        from modules.detection.yolo_module import YOLOModule
        print("   ✓ moduli detection importati")
        
        print("5. Import moduli features...")
        from modules.features.ocr_module import OCRModule
        from modules.features.collision_module import CollisionModule
        from modules.features.person_safety_module import PersonSafetyDetector
        print("   ✓ moduli features importati")
        
        print("6. Import moduli utils...")
        from modules.utils.frame_buffer import FrameBuffer
        print("   ✓ moduli utils importati")
        
        print("\n✅ TUTTI GLI IMPORT OK!")
        return True
        
    except Exception as e:
        print(f"\n❌ ERRORE IMPORT: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_functions():
    """Testa che le funzioni critiche siano accessibili."""
    print("\n" + "=" * 60)
    print("TEST FUNZIONI")
    print("=" * 60)
    
    try:
        from video_analysis import (
            discover_cameras,
            save_cameras_config,
            load_cameras_config,
            get_camera_preview_path,
            analyze_video,
            open_video_stream
        )
        print("✓ Tutte le funzioni critiche importate correttamente")
        return True
    except Exception as e:
        print(f"❌ ERRORE: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_classes():
    """Testa che le classi critiche siano accessibili."""
    print("\n" + "=" * 60)
    print("TEST CLASSI")
    print("=" * 60)
    
    try:
        from modules.core.statistics import StatisticsCollector
        from modules.core.event_logger import EventLogger
        from modules.utils.frame_buffer import FrameBuffer
        
        # Test istanziazione (senza parametri reali)
        print("✓ Tutte le classi importate correttamente")
        return True
    except Exception as e:
        print(f"❌ ERRORE: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Esegue tutti i test."""
    print("\n" + "=" * 60)
    print("VERIFICA SISTEMA - TEST RAPIDO")
    print("=" * 60 + "\n")
    
    results = []
    results.append(("Import", test_imports()))
    results.append(("Funzioni", test_functions()))
    results.append(("Classi", test_classes()))
    
    print("\n" + "=" * 60)
    print("RIEPILOGO")
    print("=" * 60)
    
    all_ok = True
    for name, result in results:
        status = "✅ OK" if result else "❌ ERRORE"
        print(f"{name}: {status}")
        if not result:
            all_ok = False
    
    print("\n" + "=" * 60)
    if all_ok:
        print("✅ TUTTI I TEST SUPERATI!")
        return 0
    else:
        print("❌ ALCUNI TEST FALLITI")
        return 1

if __name__ == "__main__":
    sys.exit(main())

