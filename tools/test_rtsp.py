"""
Script per testare diversi formati RTSP per Hikvision NVR
"""
import cv2
from urllib.parse import quote

# Configurazione NVR
IP = "192.168.1.124"
PORT = "554"
USER = "User"  # Cambia se diverso
# Inserire password al bisogno; non committare credenziali reali
PASSWORD = ""  # era presente una password hardcoded, rimossa per sicurezza

# URL-encode username e password per gestire caratteri speciali
USER_ENCODED = quote(USER, safe='')
PASSWORD_ENCODED = quote(PASSWORD, safe='')

# Formati da testare (con e senza encoding)
formats = []
# Prima prova senza encoding
formats.extend([
    f"rtsp://{USER}:{PASSWORD}@{IP}:{PORT}/Streaming/Channels/102",
    f"rtsp://{USER}:{PASSWORD}@{IP}:{PORT}/Streaming/Channels/101",
])
# Poi prova con encoding per caratteri speciali
formats.extend([
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/Streaming/Channels/102",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/Streaming/Channels/101",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/cam/realmonitor?channel=1&subtype=1",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/cam/realmonitor?channel=1&subtype=0",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/Streaming/tracks/102",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/h264/ch1/main/av_stream",
    f"rtsp://{USER_ENCODED}:{PASSWORD_ENCODED}@{IP}:{PORT}/h264/ch1/sub/av_stream",
])

print(f"Test connessione RTSP a {IP}:{PORT}")
print(f"Utente: {USER}")
print("=" * 60)

for i, url in enumerate(formats, 1):
    print(f"\n[{i}/{len(formats)}] Testando: {url.split('@')[0]}@***")
    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        if cap.isOpened():
            # Prova a leggere con timeout (max 3 secondi)
            import time
            start_time = time.time()
            ret = False
            frame = None
            
            while time.time() - start_time < 3:
                ret, frame = cap.read()
                if ret and frame is not None:
                    break
                time.sleep(0.1)
            
            if ret and frame is not None:
                print(f"  [OK] SUCCESSO! Stream funzionante.")
                print(f"  Risoluzione frame: {frame.shape[1]}x{frame.shape[0]}")
                cap.release()
                print(f"\nURL CORRETTO TROVATO: {url}")
                break
            else:
                print(f"  [X] Connesso ma nessun frame disponibile")
        else:
            print(f"  [X] Impossibile aprire stream")
    except Exception as e:
        print(f"  [X] Errore: {e}")
    finally:
        try:
            cap.release()
        except:
            pass

print("\n" + "=" * 60)
print("Test completato.")

