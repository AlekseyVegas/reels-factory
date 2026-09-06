#!/usr/bin/env python3
"""
render_reels.py — приводит готовое видео к финальному формату Reels:
1080x1920, 30fps, h264, yuv420p, faststart.

Собственная реализация для проекта reels-factory. Последний шаг пайплайна —
запускается после captions.py (или напрямую после tighten.py, если субтитры
не нужны).

Если исходное видео не вертикальное (например, экранная запись 16:9),
по умолчанию используется режим "blur": видео вписывается по ширине в кадр
1080x1920, а пустые области сверху/снизу заполняются размытым увеличенным
фоном из того же видео — так не остаётся чёрных полос. Режим "pad" делает
классические чёрные полосы, "crop" — обрезает видео по центру, заполняя
весь вертикальный кадр без полей (часть картинки по бокам теряется).

Использование:
    python render_reels.py --in final_subs.mp4 --out reel_v1.mp4
    python render_reels.py --in final_subs.mp4 --out reel_v1.mp4 --fit crop
    python render_reels.py --in final_subs.mp4 --out reel_v1.mp4 --duration 28.5
"""
import argparse
import subprocess
import sys
from pathlib import Path

TARGET_W, TARGET_H = 1080, 1920
TARGET_FPS = 30


def probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def build_filter(fit: str, src_w: int, src_h: int) -> str:
    already_vertical = src_h >= src_w  # уже портретное/квадратное видео

    if already_vertical or fit == "pad":
        # Вписать целиком, чёрные (или почти чёрные) поля по бокам/сверху-снизу
        return (
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={TARGET_FPS}"
        )

    if fit == "crop":
        return (
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={TARGET_FPS}"
        )

    # fit == "blur" (по умолчанию для горизонтального видео):
    # фон — размытая увеличенная копия на весь кадр, поверх — чёткое видео по центру
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},gblur=sigma=24[bgblur];"
        f"[fg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,setsar=1[fgscaled];"
        f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2,fps={TARGET_FPS}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fit", choices=["blur", "pad", "crop"], default="blur",
                     help="как вписывать невертикальное видео (по умолчанию blur)")
    ap.add_argument("--duration", type=float, default=None, help="жёстко зафиксировать длину, сек")
    args = ap.parse_args()

    src = Path(args.inp)
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")

    src_w, src_h = probe_dims(src)
    vf = build_filter(args.fit, src_w, src_h)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if args.duration:
        cmd += ["-t", f"{args.duration:.3f}"]
    cmd += [
        "-vf", vf,
        "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
        "-movflags", "+faststart",
        str(args.out),
    ]
    subprocess.run(cmd, check=True)

    print(f"OK: {args.out} — {TARGET_W}x{TARGET_H} @ {TARGET_FPS}fps, "
          f"исходник был {src_w}x{src_h} (режим: {'pad' if src_h >= src_w else args.fit})")


if __name__ == "__main__":
    main()
