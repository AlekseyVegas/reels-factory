#!/usr/bin/env python3
"""
captions.py — накладывает субтитры на видео по готовому words.json,
караоке-стилем: слово, которое сейчас произносится, подсвечивается цветом,
остальной текст фразы остаётся белым (как в CapCut/InVideo).

Собственная реализация для проекта reels-factory. Не требует Remotion/Node —
генерирует .ass-субтитры (формат Advanced SubStation Alpha) прямо из
 words.json и прожигает их в кадр через ffmpeg.

Шрифт по умолчанию — Montserrat Black (жирный, с засечками на кириллице,
лицензия SIL OFL 1.1, файл лежит рядом в fonts/Montserrat-Black.otf и
подключается через fontsdir — ставить его в систему не нужно, работает
"из коробки" и на Windows, и на Linux).

Чтобы длинные слова/фразы не упирались в края кадра и не выглядели
"обрезанными", размер шрифта для каждой фразы подбирается автоматически
(через реальное измерение ширины текста этим же шрифтом) под безопасную
зону с отступами по бокам; если фраза всё равно широкая — переносится на
две строки.

Использование:
    python captions.py --in tight.mp4 --words words.json --out final.mp4
    python captions.py --in tight.mp4 --words words.json --out final.mp4 \
        --words-per-phrase 3 --highlight-color FFC800 --font-size 84
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import ImageFont

HERE = Path(__file__).resolve().parent
DEFAULT_FONT_FILE = HERE.parent / "fonts" / "Montserrat-Black.otf"
DEFAULT_FONT_FAMILY = "Montserrat Black"


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


def group_into_phrases(words: list[dict], words_per_phrase: int) -> list[list[dict]]:
    return [words[i:i + words_per_phrase] for i in range(0, len(words), words_per_phrase)]


def hex_to_ass_bgr(rgb_hex: str) -> str:
    rgb = rgb_hex.strip("#")
    return rgb[4:6] + rgb[2:4] + rgb[0:2]


def measure_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    return font.getlength(text)


def best_two_line_split(words_upper: list[str], font: ImageFont.FreeTypeFont) -> tuple[list[int], list[int]]:
    """Ищет точку разрыва на две строки, которая минимизирует ширину
самой длинной из двух получившихся строк (перенос только между словами)."""
    n = len(words_upper)
    best_split = 1
    best_max_w = None
    for k in range(1, n):
        line1 = " ".join(words_upper[:k])
        line2 = " ".join(words_upper[k:])
        w = max(measure_width(font, line1), measure_width(font, line2))
        if best_max_w is None or w < best_max_w:
            best_max_w = w
            best_split = k
    return list(range(best_split)), list(range(best_split, n))


def wrap_and_fit(words_upper: list[str], font_path: Path, base_size: int, min_size: int,
                  safe_width: float, step: int = 2) -> tuple[list[list[int]], int]:
    """Подбирает максимально крупный размер шрифта, при котором фраза
(в одну или две строки) помещается в безопасную ширину кадра."""
    size = base_size
    last_lines = None
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        full = " ".join(words_upper)
        if measure_width(font, full) <= safe_width:
            return [list(range(len(words_upper)))], size
        if len(words_upper) > 1:
            line1_idx, line2_idx = best_two_line_split(words_upper, font)
            w1 = measure_width(font, " ".join(words_upper[i] for i in line1_idx))
            w2 = measure_width(font, " ".join(words_upper[i] for i in line2_idx))
            last_lines = [line1_idx, line2_idx]
            if max(w1, w2) <= safe_width:
                return last_lines, size
        size -= step
    # Ничего не влезло даже на минимальном размере (например, один
    # очень длинное слово) — возвращаем последний посчитанный вариант как есть.
    return last_lines or [list(range(len(words_upper)))], min_size


def build_ass(phrases: list[list[dict]], font_family: str, font_path: Path,
              base_size: int, min_size: int, highlight_bgr: str, default_bgr: str,
              outline_px: int, play_res: tuple[int, int], margin_h_pct: float) -> str:
    width, height = play_res
    margin_h = int(width * margin_h_pct)
    safe_width = width - 2 * margin_h

    header = f"""[Script Info]
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Default,{font_family},{base_size},&H00{default_bgr}&,&H00000000&,0,1,{outline_px},0,2,{margin_h},{margin_h},110

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines_out = []
    for phrase in phrases:
        words_upper = [w["w"].upper() for w in phrase]
        line_groups, size = wrap_and_fit(words_upper, font_path, base_size, min_size, safe_width)

        for i, w in enumerate(phrase):
            start = w["start"]
            end = phrase[i + 1]["start"] if i + 1 < len(phrase) else w["end"]
            rendered_lines = []
            for group in line_groups:
                parts = []
                for idx in group:
                    word_text = words_upper[idx]
                    if idx == i:
                        parts.append(f"{{\\1c&H{highlight_bgr}&}}{word_text}{{\\1c&H{default_bgr}&}}")
                    else:
                        parts.append(word_text)
                rendered_lines.append(" ".join(parts))
            text = "\\N".join(rendered_lines)
            lines_out.append(
                f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
                f"Default,,0,0,0,,{{\\fs{size}}}{text}"
            )

    return header + "\n".join(lines_out) + "\n"


def burn(video: Path, ass_path: Path, font_dir: Path, out: Path) -> None:
    ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
    fonts_arg = str(font_dir).replace("\\", "/").replace(":", "\\:")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(video),
         "-vf", f"ass={ass_arg}:fontsdir={fonts_arg}",
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
    ap.add_argument("--font-file", default=str(DEFAULT_FONT_FILE), help="путь к .ttf/.otf файлу шрифта")
    ap.add_argument("--font", default=DEFAULT_FONT_FAMILY, help="имя семейства шрифта для ASS Style")
    ap.add_argument("--font-size", type=int, default=84, help="базовый (максимальный) размер шрифта")
    ap.add_argument("--min-font-size", type=int, default=48, help="минимальный размер при автоподборе")
    ap.add_argument("--outline", type=int, default=5, help="толщина чёрной обводки, px")
    ap.add_argument("--color", default="FFFFFF", help="цвет обычного текста RRGGBB")
    ap.add_argument("--highlight-color", default="FFC800", help="цвет подсветки произносимого слова RRGGBB")
    ap.add_argument("--margin-pct", type=float, default=0.06,
                     help="отступ текста от левого/правого края, доля ширины кадра (0.06 = 6%%)")
    ap.add_argument("--width", type=int, default=None, help="по умолчанию берётся из самого видео")
    ap.add_argument("--height", type=int, default=None, help="по умолчанию берётся из самого видео")
    ap.add_argument("--keep-ass", action="store_true", help="не удалять .ass файл после рендера")
    args = ap.parse_args()

    video = Path(args.inp)
    if not video.exists():
        sys.exit(f"Файл не найден: {video}")

    font_path = Path(args.font_file)
    if not font_path.exists():
        sys.exit(f"Файл шрифта не найден: {font_path}")

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    if not words:
        sys.exit("words.json пустой")

    phrases = group_into_phrases(words, args.words_per_phrase)

    width, height = args.width, args.height
    if width is None or height is None:
        width, height = probe_dims(video)

    default_bgr = hex_to_ass_bgr(args.color)
    highlight_bgr = hex_to_ass_bgr(args.highlight_color)

    ass_text = build_ass(
        phrases, args.font, font_path, args.font_size, args.min_font_size,
        highlight_bgr, default_bgr, args.outline, (width, height), args.margin_pct,
    )

    if args.keep_ass:
        ass_path = Path(args.out).with_suffix(".ass")
        ass_path.write_text(ass_text, encoding="utf-8")
    else:
        fd, tmp_name = tempfile.mkstemp(suffix=".ass")
        ass_path = Path(tmp_name)
        ass_path.write_text(ass_text, encoding="utf-8")

    try:
        burn(video, ass_path, font_path.parent, Path(args.out))
    finally:
        if not args.keep_ass:
            ass_path.unlink(missing_ok=True)

    print(f"OK: {args.out} — {len(phrases)} фраз, шрифт {args.font} (файл {font_path.name})")


if __name__ == "__main__":
    main()
