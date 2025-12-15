"""Script per testare la logica di scansione telecamere e verificare che costruisca gli URL corretti."""

import json
from pathlib import Path
from urllib.parse import quote

# Carica configurazione esistente
config_file = Path("config/cameras.json")
if not config_file.exists():
    print("❌ File config/cameras.json non trovato")
    exit(1)

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

print("=" * 70)
print("VERIFICA LOGICA SCANSIONE TELECAMERE")
print("=" * 70)
print(f"\nCredenziali RTSP:")
print(f"  IP: {RTSP_IP}")
print(f"  Port: {RTSP_PORT}")
print(f"  User: {RTSP_USER}")
print(f"  Password: {'***' if RTSP_PASSWORD else '(non configurata)'}")

# Costruisci base URL come nella funzione discover_cameras
base_url = f"rtsp://{quote(RTSP_USER, safe='')}:{quote(RTSP_PASSWORD, safe='')}@{RTSP_IP}:{RTSP_PORT}"

print(f"\nBase URL: {base_url}")

# Prendi alcune telecamere dalla configurazione per testare
cameras = config.get("cameras", [])
print(f"\nTelecamere configurate: {len(cameras)}")

# Testa la logica di costruzione URL per alcune telecamere
print("\n" + "=" * 70)
print("VERIFICA COSTRUZIONE URL")
print("=" * 70)

errors = []
for cam in cameras[:10]:  # Testa le prime 10
    channel = cam.get("channel")
    stream_type = cam.get("stream_type")
    expected_url = cam.get("url")
    expected_channel_num = cam.get("channel_num")
    
    # Costruisci URL come nella funzione discover_cameras
    stream_num = 1 if stream_type == "Main" else 2
    channel_num = channel * 100 + stream_num
    constructed_url = f"{base_url}/Streaming/Channels/{channel_num:03d}"
    
    # Per canali >= 10, il formato :03d non è sufficiente, verifica
    if channel >= 10:
        # Prova anche senza padding fisso
        constructed_url_no_pad = f"{base_url}/Streaming/Channels/{channel_num}"
        if constructed_url != expected_url and constructed_url_no_pad != expected_url:
            errors.append({
                "camera": cam.get("name"),
                "expected": expected_url,
                "constructed_03d": constructed_url,
                "constructed_no_pad": constructed_url_no_pad,
                "channel_num_calc": channel_num,
                "expected_channel_num": expected_channel_num
            })
    
    status = "✓" if constructed_url == expected_url or (channel >= 10 and f"{base_url}/Streaming/Channels/{channel_num}" == expected_url) else "✗"
    print(f"{status} {cam.get('name'):30s} | Ch{channel:2d} {stream_type:4s} | "
          f"Calc: {channel_num:4d} | Expected: {expected_channel_num:4d} | "
          f"Match: {constructed_url == expected_url or (channel >= 10 and f'{base_url}/Streaming/Channels/{channel_num}' == expected_url)}")

if errors:
    print("\n" + "=" * 70)
    print("ERRORI TROVATI:")
    print("=" * 70)
    for err in errors:
        print(f"\n{err['camera']}:")
        print(f"  Expected URL:      {err['expected']}")
        print(f"  Constructed (:03d): {err['constructed_03d']}")
        print(f"  Constructed (no pad): {err['constructed_no_pad']}")
        print(f"  Channel num calc:   {err['channel_num_calc']}")
        print(f"  Expected channel:   {err['expected_channel_num']}")

# Verifica il problema del formato :03d per canali >= 10
print("\n" + "=" * 70)
print("ANALISI FORMATO CHANNEL_NUM")
print("=" * 70)

print("\nProblema identificato:")
print("  - Per canali < 10: channel_num è 3 cifre (es. 101, 102) - :03d OK")
print("  - Per canali >= 10: channel_num è 4 cifre (es. 1302, 1602) - :03d NON sufficiente")

# Testa alcuni esempi
test_cases = [
    (1, 1, "Main", 101),
    (1, 2, "Sub", 102),
    (10, 1, "Main", 1001),
    (10, 2, "Sub", 1002),
    (13, 2, "Sub", 1302),
    (16, 2, "Sub", 1602),
]

print("\nEsempi di costruzione:")
for channel, stream_num, stream_type, expected_channel_num in test_cases:
    channel_num = channel * 100 + stream_num
    url_03d = f"{base_url}/Streaming/Channels/{channel_num:03d}"
    url_no_pad = f"{base_url}/Streaming/Channels/{channel_num}"
    expected_url = f"{base_url}/Streaming/Channels/{expected_channel_num}"
    
    match_03d = url_03d == expected_url
    match_no_pad = url_no_pad == expected_url
    
    print(f"  Canale {channel:2d} {stream_type:4s}: calc={channel_num:4d}, expected={expected_channel_num:4d}")
    print(f"    :03d format: {url_03d} {'✓' if match_03d else '✗'}")
    print(f"    no pad:      {url_no_pad} {'✓' if match_no_pad else '✗'}")

print("\n" + "=" * 70)
print("CONCLUSIONE")
print("=" * 70)
print("\nIl formato :03d funziona solo per canali < 10.")
print("Per canali >= 10, bisogna usare un formato senza padding fisso o :04d.")
print("\nRaccomandazione: modificare la funzione discover_cameras per usare")
print("  url = f\"{base_url}/Streaming/Channels/{channel_num}\"")
print("  invece di")
print("  url = f\"{base_url}/Streaming/Channels/{channel_num:03d}\"")

