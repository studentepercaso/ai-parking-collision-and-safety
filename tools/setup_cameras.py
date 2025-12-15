from pathlib import Path
from typing import List, Dict, Optional
import argparse

from prova_yolo import (  # type: ignore[import-not-found]
    discover_cameras,
    save_cameras_config,
    load_cameras_config,
    get_active_cameras,
    CameraConfigurationWindow,
)


def _print_camera_summary(cameras: List[Dict[str, str]]) -> None:
    """Stampa un riassunto leggibile delle telecamere trovate/attive."""
    if not cameras:
        print("\nNessuna telecamera configurata.")
        return

    print("\nTelecamere configurate:")
    print("=" * 60)
    for idx, cam in enumerate(cameras, start=1):
        name = cam.get("name", f"Camera {idx}")
        url = cam.get("url", "-")
        channel = cam.get("channel", "-")
        stream_type = cam.get("stream_type", "-")
        active = cam.get("active", True)

        status = "ATTIVA" if active else "DISATTIVA"
        print(f"[{idx}] {name}")
        print(f"    Stato: {status}")
        print(f"    Canale: {channel} - {stream_type}")
        print(f"    URL: {url}")
        print(f"    Attiva: {status}")
        print("-" * 60)


def _print_monitor_commands(active_cameras: List[Dict[str, str]]) -> None:
    """Stampa i comandi pronti per avviare il monitoraggio con il secondo script."""
    if not active_cameras:
        return

    print("\nComandi pronti per il MONITORAGGIO (uno per telecamera attiva):")
    print("=" * 60)
    for cam in active_cameras:
        name = cam.get("name", "Camera")
        url = cam.get("url", "")
        if not url:
            continue
        print(f"# {name}")
        print(f'python monitor_cameras.py --url "{url}"')
        print("-" * 60)


def run_setup(max_channels: int = 16, timeout: float = 12.0, rescan: bool = False) -> None:
    """
    Script di SETUP/ANALISI telecamere.

    - Se esiste già un `cameras_config.json` valido, lo carica (a meno che non sia richiesto --rescan).
    - Altrimenti esegue una scansione completa dell'NVR (discover_cameras)
      e salva la configurazione.
    - Apre il pannello di configurazione per attivare/disattivare le telecamere.
    - Alla fine stampa un riassunto delle telecamere attive e salva la config.
    """
    print("\n" + "=" * 60)
    print("SETUP TELECAMERE - ANALISI E CONFIGURAZIONE")
    print("=" * 60)

    # 1. Prova a caricare una configurazione esistente (se non forzi la nuova scansione)
    all_cameras: Optional[List[Dict[str, str]]] = None
    if not rescan:
        all_cameras = load_cameras_config()

    if all_cameras:
        print("\nConfigurazione esistente trovata in 'cameras_config.json'.")
        print("Userò questa configurazione come base.")
    else:
        # 2. Nessuna configurazione o rescan: esegui scansione completa
        if rescan:
            print("\nRichiesta nuova scansione completa (--rescan).")
        else:
            print("\nNessuna configurazione trovata.")
        print("Avvio SCANSIONE COMPLETA delle telecamere sull'NVR...\n")

        all_cameras = discover_cameras(
            max_channels=max_channels,
            timeout=timeout,
            progress_callback=None,
        )

        if not all_cameras:
            print("\nNessuna telecamera trovata. Verifica:")
            print("  - IP NVR e porta in cima al file 'prova_yolo.py'")
            print("  - Username/password RTSP")
            print("  - Connessione di rete")
            return

        save_cameras_config(all_cameras)
        print(f"\n{len(all_cameras)} telecamera(e) trovate e salvate in 'cameras_config.json'.")

    # 3. Apre pannello di configurazione per attivare/disattivare telecamere
    try:
        config_window = CameraConfigurationWindow(all_cameras)
        updated_cameras = config_window.run()
    except Exception as exc:  # noqa: BLE001
        print(f"\nAvviso: impossibile aprire il pannello di configurazione: {exc}")
        print("Userò la configurazione caricata senza modifiche.")
        updated_cameras = None

    if updated_cameras:
        all_cameras = updated_cameras
        save_cameras_config(all_cameras, preserve_active_state=False)
        print("\nConfigurazione aggiornata e salvata.")

    # 4. Stampa riepilogo telecamere (tutte + attive) e comandi monitoraggio
    _print_camera_summary(all_cameras)

    active_cameras = get_active_cameras(all_cameras)
    print(f"\nTelecamere ATTIVE: {len(active_cameras)}/{len(all_cameras)}")
    _print_camera_summary(active_cameras)
    _print_monitor_commands(active_cameras)

    print("\nSetup completato.")
    print("Puoi copiare uno dei comandi sopra per avviare il monitoraggio con YOLO.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Setup telecamere: scansione iniziale + configurazione attive.\n"
            "Senza argomenti usa la configurazione esistente se presente.\n"
            "Con --rescan forza una nuova scansione completa."
        )
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Forza una nuova scansione ignorando la configurazione esistente.",
    )
    args = parser.parse_args()

    run_setup(rescan=args.rescan)