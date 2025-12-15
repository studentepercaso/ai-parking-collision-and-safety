"""Test per verificare che una singola telecamera venga trovata correttamente."""

import cv2
import time
import json
from pathlib import Path
from urllib.parse import quote

# Carica configurazione telecamere
config_file = Path("config/cameras.json")
with open(config_file, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Carica credenziali RTSP
rtsp_config_file = Path("config/rtsp.json")
if rtsp_config_file.exists():
    with open(rtsp_config_file, 'r', encoding='utf-8') as f:
        rtsp_config = json.load(f)
    RTSP_USER = rtsp_config.get("user", "User")
    RTSP_PASSWORD = rtsp_config.get("password", "")
    RTSP_IP = rtsp_config.get("ip", "192.168.1.124")
    RTSP_PORT = rtsp_config.get("port", "554")
else:
    RTSP_USER = "User"
    RTSP_PASSWORD = ""
    RTSP_IP = "192.168.1.124"
    RTSP_PORT = "554"

# Prendi una telecamera attiva dalla configurazione
cameras = config.get("cameras", [])
active_cameras = [c for c in cameras if c.get("active", False)]

if not active_cameras:
    print("Nessuna telecamera attiva trovata nella configurazione.")
    print("Testando la prima telecamera disponibile...")
    if cameras:
        test_camera = cameras[0]
    else:
        print("Nessuna telecamera configurata!")
        exit(1)
else:
    test_camera = active_cameras[0]

print("=" * 70)
print("TEST SINGOLA TELECAMERA")
print("=" * 70)
print(f"\nTelecamera di test: {test_camera.get('name')}")
print(f"URL configurato: {test_camera.get('url')}")

# Costruisci URL come nella funzione discover_cameras
channel = test_camera.get("channel")
stream_type = test_camera.get("stream_type")
stream_num = 1 if stream_type == "Main" else 2
channel_num = channel * 100 + stream_num
base_url = f"rtsp://{quote(RTSP_USER, safe='')}:{quote(RTSP_PASSWORD, safe='')}@{RTSP_IP}:{RTSP_PORT}"
constructed_url = f"{base_url}/Streaming/Channels/{channel_num}"

print(f"\nURL costruito: {constructed_url}")
print(f"Channel num: {channel_num} (canale {channel}, stream {stream_num})")

# Verifica che gli URL corrispondano
expected_url = test_camera.get("url")
if constructed_url != expected_url:
    print(f"\n⚠️  ATTENZIONE: URL costruito diverso da quello configurato!")
    print(f"   Configurato:  {expected_url}")
    print(f"   Costruito:    {constructed_url}")
    print(f"\n   Differenza probabilmente dovuta a password non configurata in rtsp.json")
    print(f"   Usando URL configurato per il test...")
    test_url = expected_url
else:
    print(f"\n✓ URL corrispondono!")
    test_url = constructed_url

# Test connessione
print("\n" + "=" * 70)
print("TEST CONNESSIONE")
print("=" * 70)

print(f"\nTentativo di connessione a: {test_url}")
print("Attendere...")

try:
    cap = cv2.VideoCapture(test_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    if not cap.isOpened():
        print("❌ ERRORE: Stream non aperto")
        cap.release()
        exit(1)
    
    print("✓ Stream aperto correttamente")
    
    # Attesa iniziale (come nella funzione discover_cameras)
    print("Attesa stabilizzazione (2 secondi)...")
    time.sleep(2.0)
    
    # Prova a leggere frame (come nella funzione discover_cameras)
    print("Tentativo lettura frame...")
    start_time = time.time()
    timeout = 12.0
    best_frame = None
    best_score = 0
    frame_count = 0
    max_frames_to_test = 30
    
    import numpy as np
    
    while time.time() - start_time < timeout and frame_count < max_frames_to_test:
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            h, w = frame.shape[:2]
            if h > 0 and w > 0:
                # Converti a scala di grigi
                if len(frame.shape) == 3:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                else:
                    gray = frame
                
                # Calcola luminosità e contrasto
                brightness = np.mean(gray)
                contrast = np.std(gray)
                
                # Calcola score
                brightness_score = min(brightness / 150.0, 1.0) * 0.7
                contrast_score = min(contrast / 40.0, 1.0) * 0.3
                combined_score = brightness_score + contrast_score
                
                min_brightness = 20
                min_contrast = 5
                
                if brightness >= min_brightness and contrast >= min_contrast:
                    if combined_score > best_score:
                        best_frame = frame.copy()
                        best_score = combined_score
                    
                    if brightness > 80 and contrast > 20:
                        break
                elif brightness > 0:
                    if best_frame is None:
                        best_frame = frame.copy()
                        best_score = 0.1
                
                frame_count += 1
                print(f"  Frame {frame_count}: brightness={brightness:.1f}, contrast={contrast:.1f}, score={combined_score:.3f}")
                time.sleep(0.2)
            else:
                time.sleep(0.1)
        else:
            time.sleep(0.1)
    
    cap.release()
    
    if best_frame is not None:
        print(f"\n✅ SUCCESSO: Frame trovato!")
        print(f"   Score: {best_score:.3f}")
        print(f"   Frame letti: {frame_count}")
        print(f"   Dimensione frame: {best_frame.shape}")
        
        # Salva frame di test
        test_output = Path("test_camera_frame.jpg")
        cv2.imwrite(str(test_output), best_frame)
        print(f"   Frame salvato in: {test_output}")
        
        print("\n✅ La telecamera verrebbe trovata dalla funzione discover_cameras!")
    else:
        print(f"\n❌ ERRORE: Nessun frame valido trovato")
        print(f"   Frame tentati: {frame_count}")
        print(f"   Timeout: {timeout} secondi")
        print("\n⚠️  La telecamera NON verrebbe trovata dalla funzione discover_cameras")
        print("   Possibili cause:")
        print("   - Stream non disponibile")
        print("   - Credenziali errate")
        print("   - Criteri di accettazione troppo restrittivi")
        exit(1)
        
except Exception as e:
    print(f"\n❌ ERRORE durante il test: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n" + "=" * 70)
print("TEST COMPLETATO CON SUCCESSO")
print("=" * 70)

