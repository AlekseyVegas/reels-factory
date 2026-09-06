#!/usr/bin/env python3
"""
tighten.py — убирает реальные паузы тишины из видео (джамп-каты по звуку).

Собственная реализация для проекта reels-factory. Не зависит от распознавания
речи — работает по чистому анализу громкости через ffmpeg (silencedetect),
поэтому это быстрый первый проход нарезки. Слова не трогает: границы резов
всегда попадают в паузу, никогда не внутрь звука.

Использование:
    python tighten.py --in raw.mp4 --out tight.mp4
    python tighten.py --in raw.mp4 --out tight.mp4 --min-silence 0.35 --keep-pad 0.07
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def find_silences(path: Path, noise_db: str, min_silence: float) -> list[tuple[float, float]]:
    """Гоняет ffmpeg silencedetect и парсит из stderr интервалы тишины."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}:d={min_silence}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    # ВАЖНО: ffmpeg иногда репортит silence_start чуть раньше нуля
    # (например, "-0.0077"), если пауза начинается прямо в первом кадре
    # записи. Без знака "-" в регулярке эта пауза терялась, счётчики
    # start/end расходились на единицу, и zip() склеивал каждый start со
    # start/end СОСЕДНЕЙ паузы — получались вложенные друг в друга куски
    # и итоговая длина больше исходной.
    log = proc.stderr
    starts = [max(0.0, float(x)) for x in re.findall(r"silence_start:\s*(-?[0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[0-9.]+)", log)]
    return list(zip(starts, ends))


def build_keep_segments(duration: float, silences: list[tuple[float, float]], keep_pad: float) -> list[tuple[float, float]]:
    """Из списка пауз строит список кусков, которые нужно ОСТАВИТЬ (с небольшим
    запасом тишины keep_pad на стыке, чтобы не было щелчков)."""
    segments = []
    cursor = 0.0
    for sil_start, sil_end in silences:
        cut_end = min(duration, sil_start + keep_pad)
        if cut_end - cursor > 0.05:
            segments.append((cursor, cut_end))
        cursor = max(cursor, sil_end - keep_pad)
    if duration - cursor > 0.05:
        segments.append((cursor, duration))
    return segments


def render(path: Path, segments: list[tuple[float, float]], out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        parts = []
        for i, (start, end) in enumerate(segments):
            part = tmp_dir / f"part_{i:04d}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(path),
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-ar", "44100",
                 str(part)],
                check=True,
            )
            parts.append(part)

        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(out)],
            check=True,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--noise", default="-30dB", help="порог тишины (по умолчанию -30dB)")
    ap.add_argument("--min-silence", type=float, default=0.35, help="мин. длина паузы для реза, сек")
    ap.add_argument("--keep-pad", type=float, default=0.07, help="сколько тишины оставить на стыке, сек")
    args = ap.parse_args()

    src = Path(args.inp)
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")

    duration = probe_duration(src)
    silences = find_silences(src, args.noise, args.min_silence)
    segments = build_keep_segments(duration, silences, args.keep_pad)

    if not segments:
        sys.exit("Не осталось ни одного куска — попробуй уменьшить --min-silence.")

    render(src, segments, Path(args.out))

    kept = sum(e - s for s, e in segments)
    print(f"OK: {args.out} — было {duration:.1f}с, стало {kept:.1f}с "
          f"(вырезано {duration - kept:.1f}с тишины, {len(segments)} кусков)")


if __name__ == "__main__":
    main()
