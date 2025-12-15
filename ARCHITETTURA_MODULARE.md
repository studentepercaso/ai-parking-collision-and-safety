# Architettura Modulare - Sistema di Monitoraggio YOLO

## Panoramica

Il sistema è stato refactorizzato in un'architettura modulare con caricamento lazy delle funzionalità. Questo permette:
- **Avvio veloce**: nessun modello caricato all'avvio
- **Memoria ottimizzata**: solo moduli necessari vengono caricati
- **Performance migliori**: modalità "solo visualizzazione" senza YOLO
- **Modularità**: facile aggiungere/rimuovere funzionalità
- **Selezione dinamica modelli**: uso del modello più leggero in base alle funzionalità richieste

## Struttura Moduli

```
modules/
├── core/                    # Moduli sempre caricati (leggeri)
│   ├── statistics.py        # StatisticsCollector
│   └── event_logger.py      # EventLogger
│
├── detection/               # Moduli di detection opzionali
│   └── yolo_module.py       # YOLO lazy loading e selezione modelli
│
└── features/                # Funzionalità opzionali
    ├── ocr_module.py        # OCR + LicensePlateManager (configurabile)
    ├── collision_module.py  # CollisionDetector (solo veicoli)
    └── person_safety_module.py  # Person Safety (INDIPENDENTE)
```

## Selezione Modelli YOLO

Il sistema seleziona automaticamente il modello YOLO più adatto (o permette selezione manuale):

| Modello | Dimensione | Velocità | Accuratezza | Uso consigliato |
|---------|-----------|----------|-------------|-----------------|
| `yolo11n.pt` | ~6 MB | ⚡⚡⚡ | ⭐⭐ | Tracking base, visualizzazione |
| `yolo11s.pt` | ~22 MB | ⚡⚡ | ⭐⭐⭐ | Tracking migliorato |
| `yolo11m.pt` | ~52 MB | ⚡ | ⭐⭐⭐⭐ | Accuratezza media |
| `yolo11n-seg.pt` | ~6 MB | ⚡⚡ | ⭐⭐ | Collision detection (maschere) |

**Logica Automatica:**
1. Se abilitato **Collision Detection** → usa `yolo11n-seg.pt` (serve segmentazione)
2. Se abilitato **Lettura Targhe** → usa `yolo11s.pt` (migliore precisione per detection auto piccole/lontane)
3. Altrimenti (tracking base/persone) → usa `yolo11n.pt` (più veloce)

## Ottimizzazione OCR

Il modulo OCR supporta configurazioni per ridurre l'uso di memoria:
- **Lingua**: Selezionabile (solo 'en' è più leggero di 'en+it')
- **Quantizzazione**: Abilitata di default (riduce memoria modello)
- **Lazy Loading**: Caricato solo quando necessario

## Moduli Core (Sempre Caricati)

### StatisticsCollector
- **File**: `modules/core/statistics.py`
- **Scopo**: Raccoglie statistiche real-time (FPS, oggetti, eventi)
- **Uso**: Sempre disponibile, thread-safe

### EventLogger
- **File**: `modules/core/event_logger.py`
- **Scopo**: Logging eventi strutturati in JSON
- **Uso**: Sempre disponibile, thread-safe

## Moduli Opzionali

### YOLO Module
- **File**: `modules/detection/yolo_module.py`
- **Scopo**: Caricamento lazy del modello YOLO
- **Caricamento**: Solo se `enable_yolo=True` o se richiesto da altri moduli
- **Metodi**:
  - `get_model(model_name)`: Carica modello (lazy)
  - `get_optimal_model(features)`: Seleziona modello in base a feature
  - `is_loaded()`: Verifica se caricato
  - `unload()`: Scarica per liberare memoria

### OCR Module
- **File**: `modules/features/ocr_module.py`
- **Scopo**: Lettura targhe con EasyOCR
- **Caricamento**: Solo se `enable_plates=True`
- **Dipendenze**: Richiede YOLO
- **Classi**:
  - `OCRModule`: Gestisce reader EasyOCR (lazy, configurabile)
  - `LicensePlateManager`: Gestisce lettura e caching targhe

### Collision Module
- **File**: `modules/features/collision_module.py`
- **Scopo**: Rilevamento collisioni tra veicoli
- **Caricamento**: Solo se `enable_collision=True`
- **Dipendenze**: Richiede YOLO
- **Nota**: Solo veicoli, NON include Person Safety

### Person Safety Module
- **File**: `modules/features/person_safety_module.py`
- **Scopo**: Rilevamento loitering e cadute persone
- **Caricamento**: Solo se `enable_person_safety=True`
- **Dipendenze**: Richiede YOLO, **INDIPENDENTE** da CollisionDetector
- **Funzionalità**:
  - Person Loitering: rileva persone che stanno troppo tempo in un'area
  - Person Fall Detection: rileva cadute basandosi su aspect ratio e drop velocità

## Uso in `analyze_video`

La funzione `analyze_video` ora supporta moduli opzionali:

```python
analyze_video(
    video_path=Path("video.mp4"),
    model_name="auto",              # O nome specifico (es. "yolo11n.pt")
    enable_plates=False,            # DEFAULT: False
    enable_collision=False,         # DEFAULT: False
    enable_person_safety=False,      # DEFAULT: False
    # ... altri parametri
)
```

## Dipendenze

```
YOLO Module
    ├──→ OCR Module (targhe)
    ├──→ Collision Module (collisioni veicoli)
    └──→ Person Safety Module (INDIPENDENTE!)
```

## Retrocompatibilità

Le classi `StatisticsCollector`, `EventLogger`, `LicensePlateManager` sono ancora presenti in `prova_yolo.py` per retrocompatibilità, ma `analyze_video` ora usa i moduli.

## Test

Eseguire `python verify_system.py` per verificare:
- Import moduli
- Funzionalità core
- YOLO, OCR, Person Safety modules
- Ridondanze
- Documentazione
