import argparse
from typing import Optional

from prova_yolo import (  # type: ignore[import-not-found]
    main as yolo_main,
    select_camera_interactive,
)


def run_monitor(
    model_name: str = "yolo11n.pt",
    enable_plates: bool = False,
    conf: float = 0.6,
    imgsz: int = 1280,
    direct_url: Optional[str] = None,
) -> None:
    """
    Script di MONITORAGGIO telecamere.

    Modalità:
    - Se viene passato --url, usa direttamente quell'URL RTSP (o altra sorgente supportata).
    - Altrimenti apre il pannello di selezione telecamera basato su `cameras_config.json`
      (solo telecamere attive) e avvia lo streaming real time su quella selezionata.
    """
    print("\n" + "=" * 60)
    print("MONITORAGGIO TELECAMERE - YOLO STREAMING")
    print("=" * 60)

    stream_source: Optional[str] = direct_url

    if stream_source is None:
        print("\nApro il pannello per la selezione della telecamera (solo ATTIVE)...")
        selected_url = select_camera_interactive()

        if not selected_url:
            print("\nNessuna telecamera selezionata. Uscita.")
            return

        stream_source = selected_url

    print(f"\nSorgente selezionata: {stream_source}")
    print("Avvio monitoraggio in tempo reale con YOLO...\n")

    # Usiamo direttamente la funzione main già presente in prova_yolo.py
    yolo_main(
        image_filename=None,
        model_name=model_name,
        video_filename=None if stream_source else None,
        enable_plates=enable_plates,
        stream_source=stream_source,
        conf=conf,
        imgsz=imgsz,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Monitoraggio telecamere con YOLO.\n"
            "- Senza argomenti apre il pannello di selezione telecamera (da cameras_config.json).\n"
            "- Con --url puoi specificare direttamente un URL RTSP/HTTP/webcam/file."
        )
    )

    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="URL/sorgente video diretta (RTSP, HTTP, index webcam, file). Se non specificato, viene usato il pannello delle telecamere attive.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n.pt",
        help="Nome del modello YOLO da usare (default: yolo11n.pt).",
    )
    parser.add_argument(
        "--enable-plates",
        action="store_true",
        help="Abilita la lettura targhe (più lenta, usa EasyOCR se disponibile).",
    )
    parser.add_argument(
        "--enable-collision",
        action="store_true",
        help="Abilita il rilevamento collisioni auto-auto (sperimentale).",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.6,
        help="Soglia di confidenza per lo streaming real time (default: 0.6).",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=1280,
        help="Dimensione input per YOLO (default: 1280). Valori comuni: 640, 960, 1280, 1920.",
    )

    args = parser.parse_args()

    run_monitor(
        model_name=args.model,
        enable_plates=args.enable_plates,
        # collisioni gestite da prova_yolo.main tramite flag,
        # qui passiamo solo il flag fino alla CLI principale.
        conf=args.conf,
        imgsz=args.imgsz,
        direct_url=args.url,
    )


