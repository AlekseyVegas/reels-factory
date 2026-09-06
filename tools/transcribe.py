#!/usr/bin/env python3
"""
transcribe.py — пословная транскрипция видео/аудио с таймкодами.

Собственная реализация для проекта reels-factory. Даёт на выходе плоский
JSON-список [{"w": "слово", "start": сек, "end": сек}, ...] — единый источник
правды для нарезки по паузам (tighten.py) и субтитров (captions.py).

Движок распознавания — whisper.cpp (offline, whisper-cli). Путь к бинарнику
и к модели не захардкожены — задаются через переменные окружения или флаги,
чтобы скрипт одинаково работал на macOS/Linux/Windows(WSL) независимо от того,
куда именно был установлен whisper.cpp.

Использование:
    python transcribe.py --in video.mp4 --out words.json
    python transcribe.py --in video.mp4 --out words.json --lang ru \
        --whisper-bin /path/to/whisper-cli --model /path/to/ggml-medium.bin

Переменные окружения (альтернатива флагам):
    WHISPER_CLI_BIN   — путь к бинарнику whisper-cli
    WHISPER_MODEL     — путь к файлу модели ggml-*.bin
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def default_whisper_bin() -> str:
    return os.environ.get("WHISPER_CLI_BIN", "whisper-cli")


def default_model() -> str:
    env = os.environ.get("WHISPER_MODEL")
    if env:
        return env
    return str(Path.home() / ".whisper-models" / "ggml-medium.bin")


def extract_mono_wav(src: Path, sample_rate: int = 16000) -> Path:
    """Достаём из видео/аудио 16кГц mono WAV — формат, который ждёт whisper.cpp."""
    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = Path(tmp_path)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def run_whisper_cpp(wav: Path, whisper_bin: str, model: str, lang: str) -> list[dict]:
    if not Path(model).exists():
        sys.exit(f"Модель не найдена: {model}\n"
                  f"Скачай её (см. docs/setup.md) или укажи --model / WHISPER_MODEL.")

    fd, base = tempfile.mkstemp()
    os.close(fd)
    base_path = Path(base)
    json_path = base_path.with_suffix(base_path.suffix + ".json")

    cmd = [
        whisper_bin,
        "-m", model,
        "-f", str(wav),
        "-l", lang,
        "-ml", "1",   # одно слово = один сегмент
        "-sow",       # split on word
        "-oj",        # вывод в JSON
        "-of", str(base_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit(f"Не найден бинарник whisper-cli: {whisper_bin}\n"
                  f"Укажи путь через --whisper-bin или переменную WHISPER_CLI_BIN.")

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    words = []
    for segment in raw.get("transcription", []):
        text = (segment.get("text") or "").strip()
        offsets = segment.get("offsets") or {}
        if text and "from" in offsets:
            words.append({
                "w": text,
                "start": offsets["from"] / 1000.0,
                "end": offsets["to"] / 1000.0,
            })
    json_path.unlink(missing_ok=True)
    return words


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="исходное видео/аудио")
    ap.add_argument("--out", required=True, help="куда писать words.json")
    ap.add_argument("--lang", default="ru", help="язык речи (по умолчанию ru)")
    ap.add_argument("--whisper-bin", default=None, help="путь к whisper-cli")
    ap.add_argument("--model", default=None, help="путь к ggml-модели")
    args = ap.parse_args()

    src = Path(args.inp)
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")

    whisper_bin = args.whisper_bin or default_whisper_bin()
    model = args.model or default_model()

    wav = extract_mono_wav(src)
    try:
        words = run_whisper_cpp(wav, whisper_bin, model, args.lang)
    finally:
        wav.unlink(missing_ok=True)

    if not words:
        sys.exit("Транскрипт пустой — проверь звук в исходном файле.")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")

    duration = words[-1]["end"]
    print(f"OK: {out_path} — {len(words)} слов, {duration:.1f} сек")


if __name__ == "__main__":
    main()
