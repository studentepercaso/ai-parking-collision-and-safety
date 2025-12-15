"""
Script di verifica completo del sistema modulare.
Verifica:
1. Variabili/funzioni non usate
2. Documentazione
3. Ridondanze
4. Test moduli
"""

import sys
from pathlib import Path
import importlib.util

# Aggiungi root al path
sys.path.append(str(Path(__file__).parent.parent))

def test_module_imports():
    """Testa import di tutti i moduli."""
    print("=" * 60)
    print("TEST 1: Verifica Import Moduli")
    print("=" * 60)
    
    modules_to_test = [
        ("modules.core.statistics", "StatisticsCollector"),
        ("modules.core.event_logger", "EventLogger"),
        ("modules.detection.yolo_module", "YOLOModule"),
        ("modules.features.ocr_module", "OCRModule"),
        ("modules.features.ocr_module", "LicensePlateManager"),
        ("modules.features.collision_module", "CollisionModule"),
        ("modules.features.person_safety_module", "PersonSafetyDetector"),
    ]
    
    errors = []
    for module_name, class_name in modules_to_test:
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                errors.append(f"[ERR] Modulo non trovato: {module_name}")
                continue
            
            module = importlib.import_module(module_name)
            if not hasattr(module, class_name):
                errors.append(f"[ERR] Classe {class_name} non trovata in {module_name}")
            else:
                print(f"[OK] {module_name}.{class_name}")
        except Exception as e:
            errors.append(f"[ERR] Errore import {module_name}: {e}")
    
    if errors:
        print("\nERRORI:")
        for err in errors:
            print(f"  {err}")
        return False
    else:
        print("\n✅ Tutti i moduli importati correttamente!")
        return True

def test_core_functionality():
    """Testa funzionalità base dei moduli core."""
    print("\n" + "=" * 60)
    print("TEST 2: Verifica Funzionalità Core")
    print("=" * 60)
    
    try:
        from modules.core.statistics import StatisticsCollector
        from modules.core.event_logger import EventLogger
        
        # Test StatisticsCollector
        stats = StatisticsCollector()
        stats.update_frame(num_cars=2, num_persons=1, car_ids=[1, 2], person_ids=[10])
        stats_data = stats.get_stats()
        assert stats_data["current_objects"]["cars"] == 2
        assert stats_data["current_objects"]["persons"] == 1
        print("[OK] StatisticsCollector funziona")
        
        # Test EventLogger
        log_file = Path("test_log.json")
        logger = EventLogger(log_file)
        logger.log("test_event", "Test message", track_id=1)
        logger.save()
        assert log_file.exists()
        log_file.unlink()  # Pulisci
        print("[OK] EventLogger funziona")
        
        return True
    except Exception as e:
        print(f"❌ Errore test core: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_yolo_module():
    """Testa YOLO Module (senza caricare modello)."""
    print("\n" + "=" * 60)
    print("TEST 3: Verifica YOLO Module")
    print("=" * 60)
    
    try:
        from modules.detection.yolo_module import YOLOModule
        
        # Test metodi senza caricare modello
        assert not YOLOModule.is_loaded()
        assert YOLOModule.get_loaded_model_name() is None
        print("[OK] YOLOModule metodi base funzionano")
        
        # Test unload (non dovrebbe fare nulla se non caricato)
        YOLOModule.unload()
        print("[OK] YOLOModule.unload() funziona")
        
        return True
    except Exception as e:
        print(f"❌ Errore test YOLO module: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ocr_module():
    """Testa OCR Module (senza caricare reader)."""
    print("\n" + "=" * 60)
    print("TEST 4: Verifica OCR Module")
    print("=" * 60)
    
    try:
        from modules.features.ocr_module import OCRModule
        
        # Test metodi senza caricare reader
        assert not OCRModule.is_loaded()
        print("✅ OCRModule metodi base funzionano")
        
        # Test unload
        OCRModule.unload()
        print("✅ OCRModule.unload() funziona")
        
        return True
    except Exception as e:
        print(f"❌ Errore test OCR module: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_person_safety_module():
    """Testa Person Safety Module."""
    print("\n" + "=" * 60)
    print("TEST 5: Verifica Person Safety Module")
    print("=" * 60)
    
    try:
        from modules.features.person_safety_module import PersonSafetyDetector
        
        # Crea detector
        detector = PersonSafetyDetector(
            enable_loitering=True,
            enable_fall=True,
            loiter_seconds=20.0,
            debug_mode=False
        )
        
        # Test process_persons con lista vuota
        events = detector.process_persons(
            camera_id="test",
            persons=[],
            timestamp=0.0,
            frame_shape=(720, 1280)
        )
        assert events == []
        print("[OK] PersonSafetyDetector creazione e process_persons funzionano")
        
        return True
    except Exception as e:
        print(f"❌ Errore test Person Safety module: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_redundancies():
    """Verifica file/classi ridondanti."""
    print("\n" + "=" * 60)
    print("TEST 6: Verifica Ridondanze")
    print("=" * 60)
    
    issues = []
    
    # Verifica se collision_detector.py nella root è solo wrapper
    collision_wrapper = Path("collision_detector.py")
    if collision_wrapper.exists():
        content = collision_wrapper.read_text(encoding='utf-8')
        if "from collision_detector.detector import" in content:
            print("[OK] collision_detector.py è wrapper (OK)")
        else:
            issues.append("[WARN] collision_detector.py potrebbe essere ridondante")
    
    # Verifica classi duplicate in prova_yolo.py
    prova_yolo = Path("prova_yolo.py")
    if prova_yolo.exists():
        content = prova_yolo.read_text(encoding='utf-8')
        if "class StatisticsCollector:" in content:
            issues.append("[WARN] StatisticsCollector ancora definita in prova_yolo.py (dovrebbe usare moduli)")
        if "class EventLogger:" in content:
            issues.append("[WARN] EventLogger ancora definita in prova_yolo.py (dovrebbe usare moduli)")
        if "class LicensePlateManager:" in content:
            issues.append("[WARN] LicensePlateManager ancora definita in prova_yolo.py (dovrebbe usare moduli)")
    
    if issues:
        print("PROBLEMI TROVATI:")
        for issue in issues:
            print(f"  {issue}")
        return False
    else:
        print("[OK] Nessuna ridondanza critica trovata")
        return True

def check_documentation():
    """Verifica documentazione."""
    print("\n" + "=" * 60)
    print("TEST 7: Verifica Documentazione")
    print("=" * 60)
    
    modules_to_check = [
        "modules/core/statistics.py",
        "modules/core/event_logger.py",
        "modules/detection/yolo_module.py",
        "modules/features/ocr_module.py",
        "modules/features/collision_module.py",
        "modules/features/person_safety_module.py",
    ]
    
    issues = []
    for module_path in modules_to_check:
        path = Path(module_path)
        if not path.exists():
            issues.append(f"❌ File non trovato: {module_path}")
            continue
        
        content = path.read_text(encoding='utf-8')
        
        # Verifica docstring modulo
        if not content.strip().startswith('"""') and not content.strip().startswith("'''"):
            issues.append(f"[WARN] {module_path}: manca docstring modulo")
        
        # Verifica docstring classi
        if "class " in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith("class "):
                    # Verifica se c'è docstring dopo
                    has_docstring = False
                    for j in range(i+1, min(i+5, len(lines))):
                        if '"""' in lines[j] or "'''" in lines[j]:
                            has_docstring = True
                            break
                    if not has_docstring:
                        class_name = line.split("class ")[1].split("(")[0].split(":")[0].strip()
                        issues.append(f"[WARN] {module_path}: classe {class_name} senza docstring")
    
    if issues:
        print("PROBLEMI TROVATI:")
        for issue in issues:
            print(f"  {issue}")
        return False
    else:
        print("[OK] Documentazione base presente")
        return True

def main():
    """Esegue tutti i test."""
    print("\n" + "=" * 60)
    print("VERIFICA COMPLETA SISTEMA MODULARE")
    print("=" * 60)
    
    results = []
    
    results.append(("Import Moduli", test_module_imports()))
    results.append(("Funzionalità Core", test_core_functionality()))
    results.append(("YOLO Module", test_yolo_module()))
    results.append(("OCR Module", test_ocr_module()))
    results.append(("Person Safety Module", test_person_safety_module()))
    results.append(("Ridondanze", check_redundancies()))
    results.append(("Documentazione", check_documentation()))
    
    print("\n" + "=" * 60)
    print("RIEPILOGO")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print(f"\nTotale: {passed}/{total} test passati")
    
    if passed == total:
        print("\n[SUCCESS] TUTTI I TEST PASSATI!")
        return 0
    else:
        print(f"\n[WARN] {total - passed} test falliti")
        return 1

if __name__ == "__main__":
    sys.exit(main())

