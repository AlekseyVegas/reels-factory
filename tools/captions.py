#!/usr/bin/env python3
"""
captions.py — накладывает субтитры на видео по готовому words.json.

Собственная реализация для проекта reels-factory. Не требует Remotion/Node —
генерирует .ass-субтитры (формат Advanced SubStation Alpha) прямо из words.json
и прожигает их в кадр через ffmpeg. Слова группируются по фразам (по умолчанию
3 слова на фразу). Размер холста под субтитры подхватывается автоматически из
самого видео (важно: PlayResX/Y в .ass обязаны совпадать с реальным разрешением
видео, иначе текст рендерится с искажениями).

Использование:
    python captions.py --in tight.mp4 --words words.json --out final.mp4
    python captions.py --in tight.mp4 --words words.json --out final.mp4 \
        --words-per-phrase 4 --font "Arial Bold" --font-size 64 --color FFFFFF
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def seconds_to_ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def group_into_phrases(words: list[dict], words_per_phrase: int) -> list[dict]:
    phrases = []
    for i in range(0, len(words), words_per_phrase):
        chunk = words[i:i + words_per_phrase]
        phrases.append({
            "text": " ".join(w["w"] for w in chunk).upper(),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return phrases


def build_ass(phrases: list[dict], font: str, font_size: int, color_bgr_hex: str,
              play_res: tuple[int, int]) -> str:
    # ВАЖНО: Format в [Events] обязан перечислять РОВНО те поля, что реально
    # присутствуют в строках Dialogue ниже (10 стандартных полей ASS) — если
    # объявить только часть полей, лишние запятые из Dialogue "утекут" в текст.
    header = f"""[Script Info]
PlayResX: {play_res[0]}
PlayResY: {play_res[1]}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginV
Style: Default,{font},{font_size},&H00{color_bgr_hex}&,&H00000000&,1,1,3,0,2,120

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for p in phrases:
        start = seconds_to_ass_time(p["start"])
        end = seconds_to_ass_time(p["end"])
        text = p["text"].replace("\n", " ")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


def burn(video: Path, ass_path: Path, out: Path) -> None:
    # ffmpeg ass= фильтр требует экранированные ':' в пути на некоторых системах
    ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(video),
         "-vf", f"ass={ass_arg}",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "copy",
         str(out)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--words", required=True, help="words.json от transcribe.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--words-per-phrase", type=int, default=3)
    ap.add_argument("--font", default="Arial Bold")
    ap.add_argument("--font-size", type=int, default=64)
    ap.add_argument("--color", default="FFFFFF", help="цвет текста RRGGBB (обычный hex, не BGR — конвертируем сами)")
    ap.add_argument("--width", type=int, default=None, help="по умолчанию берётся из самого видео")
    ap.add_argument("--height", type=int, default=None, help="по умолчанию берётся из самого видео")
    ap.add_argument("--keep-ass", action="store_true", help="не удалять .ass файл после рендера")
    args = ap.parse_args()

    video = Path(args.inp)
    if not video.exists():
        sys.exit(f"Файл не найден: {video}")

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    if not words:
        sys.exit("words.json пустой")

    phrases = group_into_phrases(words, args.words_per_phrase)

    # RRGGBB -> BBGGRR, как требует ASS
    rgb = args.color.strip("#")
    bgr = rgb[4:6] + rgb[2:4] + rgb[0:2]

    width, height = args.width, args.height
    if width is None or height is None:
        width, height = probe_dims(video)

    ass_text = build_ass(phrases, args.font, args.font_size, bgr, (width, height))

    if args.keep_ass:
        ass_path = Path(args.out).with_suffix(".ass")
        ass_path.write_text(ass_text, encoding="utf-8")
    else:
        fd, tmp_name = tempfile.mkstemp(suffix=".ass")
        ass_path = Path(tmp_name)
        ass_path.write_text(ass_text, encoding="utf-8")

    try:
        burn(video, ass_path, Path(args.out))
    finally:
        if not args.keep_ass:
            ass_path.unlink(missing_ok=True)

    print(f"OK: {args.out} — {len(phrases)} фраз субтитров")


if __name__ == "__main__":
    main()
