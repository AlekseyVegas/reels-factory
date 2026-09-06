#!/usr/bin/env python3
"""
broll.py — вставляет b-roll (перебивки) поверх основного видео по таймкодам,
не трогая звук (голос продолжает звучать под перебивкой).

Собственная реализация для проекта reels-factory. Запускается после
tighten.py/transcribe.py и до captions.py — чтобы субтитры потом прожигались уже
поверх готового с перебивками видео и не терялись под ними.

Два режима:

1) --auto — сам решает, куда и что вставлять: берёт видео из --broll-dir
   по кругу и расставляет их через равные интервалы. Одновременно
   сохраняет получившийся план в JSON (--out-plan), чтобы его можно было открыть,
   поправить вручную (заменить клип, подвинуть тайминг) и переиспользовать.

2) --plan plan.json — использует готовый план вставок, ничего не придумывая.
   Формат plan.json — список объектов:
       [{"start": 3.0, "end": 6.5, "clip": "broll/city.mp4"}, ...]

Пример:
    python broll.py --in tight.mp4 --broll-dir broll/ --auto \
        --interval 8 --duration 2.5 --out with_broll.mp4 --out-plan plan.json

    python broll.py --in tight.mp4 --plan plan.json --out with_broll.mp4
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def list_broll_clips(broll_dir: Path) -> list[Path]:
    clips = sorted(
        p for p in broll_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )
    if not clips:
        sys.exit(f"В папке {broll_dir} не найдено видеофайлов ({', '.join(sorted(VIDEO_EXTS))})")
    return clips


def build_auto_plan(main_duration: float, clips: list[Path], interval: float,
                     duration: float, margin: float) -> list[dict]:
    """Расставляет клипы по кругу через равные интервалы, отступив от
    начала и конца видео на margin секунд, чтобы не перебивать вступление/концовку."""
    plan = []
    t = margin
    i = 0
    while t + duration <= main_duration - margin:
        plan.append({
            "start": round(t, 2),
            "end": round(t + duration, 2),
            "clip": str(clips[i % len(clips)]),
        })
        i += 1
        t += interval
    if not plan:
        sys.exit(
            "Не удалось разместить ни одной вставки — видео короче, чем "
            f"margin*2 + duration ({margin * 2 + duration:.1f}с). Уменьши --duration/--margin."
        )
    return plan


def build_filter(plan: list[dict], w: int, h: int) -> tuple[str, list[str]]:
    """Строит filter_complex граф: каждая b-roll вставка — отдельный вход,
    зациклен на всякий случай (-stream_loop -1), обрезан до нужной длины
    и сдвинут по времени так, чтобы совпасть со своим окном на основном
    видео, затем последовательно наложен через overlay c enable=between(...).
    Возвращает (filter_complex, доп. input-аргументы для ffmpeg)."""
    extra_inputs = []
    parts = []
    for i, seg in enumerate(plan):
        dur = seg["end"] - seg["start"]
        extra_inputs += ["-stream_loop", "-1", "-i", seg["clip"]]
        parts.append(
            f"[{i + 1}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,"
            f"trim=duration={dur:.3f},setpts=PTS-STARTPTS+{seg['start']:.3f}/TB[b{i}]"
        )

    label_prev = "0:v"
    overlay_lines = []
    for i, seg in enumerate(plan):
        out_label = f"v{i}" if i < len(plan) - 1 else "vout"
        overlay_lines.append(
            f"[{label_prev}][b{i}]overlay=enable='between(t,{seg['start']:.3f},{seg['end']:.3f})'[{out_label}]"
        )
        label_prev = out_label

    filter_complex = ";".join(parts + overlay_lines)
    return filter_complex, extra_inputs


def render(main: Path, plan: list[dict], out: Path) -> None:
    w, h = probe_dims(main)
    filter_complex, extra_inputs = build_filter(plan, w, h)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(main)] + extra_inputs + [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--broll-dir", help="папка с видео для перебивок (для --auto)")
    ap.add_argument("--auto", action="store_true", help="автоматически расставить перебивки по кругу")
    ap.add_argument("--interval", type=float, default=8.0, help="через сколько секунд вставлять перебивку (--auto)")
    ap.add_argument("--duration", type=float, default=2.5, help="длительность одной вставки, сек (--auto)")
    ap.add_argument("--margin", type=float, default=2.0, help="отступ от начала/конца видео, сек (--auto)")
    ap.add_argument("--plan", help="готовый JSON-план вставок (вместо --auto)")
    ap.add_argument("--out-plan", help="куда сохранить сгенерированный план (--auto)")
    args = ap.parse_args()

    main_video = Path(args.inp)
    if not main_video.exists():
        sys.exit(f"Файл не найден: {main_video}")

    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        if not plan:
            sys.exit("План пустой")
    elif args.auto:
        if not args.broll_dir:
            sys.exit("--auto требует --broll-dir")
        broll_dir = Path(args.broll_dir)
        if not broll_dir.is_dir():
            sys.exit(f"Папка не найдена: {broll_dir}")
        clips = list_broll_clips(broll_dir)
        duration = probe_duration(main_video)
        plan = build_auto_plan(duration, clips, args.interval, args.duration, args.margin)
        if args.out_plan:
            Path(args.out_plan).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    else:
        sys.exit("Укажи либо --plan plan.json, либо --auto --broll-dir <папка>")

    render(main_video, plan, Path(args.out))
    print(f"OK: {args.out} — {len(plan)} вставок b-roll")


if __name__ == "__main__":
    main()
