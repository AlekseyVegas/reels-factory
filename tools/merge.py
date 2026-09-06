#!/usr/bin/env python3
"""
merge.py — склеивает несколько видеофайлов (например, части одной записи)
в один, прежде чем пускать его в остальной пайплайн.

Собственная реализация для проекта reels-factory. Это шаг 0 — самый первый,
до tighten.py: если ролик снят несколькими кусками (запись прервалась, переписывал
часть, снимал по сценам), сначала склеиваем всё в один файл, а дальше работаем
с ним как обычно.

Почему нельзя просто склеить как есть: если куски сняты с разным
разрешением/fps/кодеком (это часто бывает — например, один дубль переснят
на другом устройстве или в других настройках), прямая склейка либо упадёт
с ошибкой, либо даст рассинхрон звука и рывки. Поэтому каждый кусок сначала
приводится к общему знаменателю (разрешение, fps, кодек, частота
дискретизации звука), и только потом клеится через concat.

Порядок склейки — по порядку перечисления файлов в --in (или по алфавиту
имён файлов, если используешь --in-dir).

Использование:
    python merge.py --in part1.mp4 part2.mp4 part3.mp4 --out full.mp4
    python merge.py --in-dir parts/ --out full.mp4
    python merge.py --in-dir parts/ --out full.mp4 --width 1080 --height 1920 --fps 30
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return bool(out)


def normalize(src: Path, dst: Path, w: int, h: int, fps: int) -> None:
    """Приводит один кусок к общему формату: разрешение (letterbox, без
    обрезки — контент целиком сохраняется), fps, h264/aac, 48кГц звук.
    Если в куске нет звука — добавляет тишину, чтобы concat не разъехался."""
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if has_audio(src):
        cmd += ["-vf", vf, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dst)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf", vf, "-shortest",
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dst)]
    subprocess.run(cmd, check=True)


def concat(normalized: list[Path], out: Path) -> None:
    fd, list_path = tempfile.mkstemp(suffix=".txt")
    with open(fd, "w", encoding="utf-8") as f:
        for p in normalized:
            # экранируем одинарные кавычки на случай спецсимволов в пути
            f.write(f"file '{str(p).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", str(out)],
            check=True,
        )
    finally:
        Path(list_path).unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inputs", nargs="+", help="файлы по порядку склейки")
    ap.add_argument("--in-dir", help="папка с частями — берутся все видео по алфавиту имён")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=None, help="по умолчанию берётся из первого файла")
    ap.add_argument("--height", type=int, default=None, help="по умолчанию берётся из первого файла")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    if args.in_dir:
        d = Path(args.in_dir)
        if not d.is_dir():
            sys.exit(f"Папка не найдена: {d}")
        files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    elif args.inputs:
        files = [Path(p) for p in args.inputs]
    else:
        sys.exit("Укажи либо --in file1 file2 ..., либо --in-dir <папка>")

    if len(files) < 2:
        sys.exit("Нужно минимум 2 видеофайла для склейки")
    for f in files:
        if not f.exists():
            sys.exit(f"Файл не найден: {f}")

    print("Порядок склейки:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")

    width, height = args.width, args.height
    if width is None or height is None:
        width, height = probe_dims(files[0])

    tmpdir = Path(tempfile.mkdtemp(prefix="merge_"))
    normalized = []
    try:
        for i, f in enumerate(files):
            dst = tmpdir / f"part_{i:03d}.mp4"
            normalize(f, dst, width, height, args.fps)
            normalized.append(dst)

        concat(normalized, Path(args.out))
    finally:
        for p in normalized:
            p.unlink(missing_ok=True)
        try:
            tmpdir.rmdir()
        except OSError:
            pass

    print(f"OK: {args.out} — склеено {len(files)} частей, {width}x{height} @ {args.fps}fps")


if __name__ == "__main__":
    main()
