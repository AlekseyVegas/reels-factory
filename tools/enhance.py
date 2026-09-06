#!/usr/bin/env python3
"""
enhance.py — улучшает качество картинки видео перед дальнейшей обработкой:
убирает цифровой шум (частая проблема фронтальных камер при слабом свете),
слегка повышает резкость и поправляет экспозицию/контраст. По желанию
может честно увеличить разрешение через открытую нейросеть (апскейл).

Собственная реализация для проекта reels-factory, поверх открытых инструментов
ffmpeg (фильтры hqdn3d/unsharp/eq — часть самого ffmpeg) и, опционально,
Video2X (github.com/k4yt3x/video2x, AGPL-3.0, модели Real-ESRGAN) — оба
бесплатные и работают полностью локально, без облака.

Место в пайплайне: сразу после merge.py (или сразу на сыром видео, если
оно снято одним куском) и ДО tighten.py — чтобы дальше по цепочке уже шла
улучшенная картинка.

Использование:
    # Лёгкое улучшение по умолчанию (шум + резкость + экспозиция) — быстро,
    # работает всегда, ничего дополнительно ставить не нужно
    python enhance.py --in raw.mp4 --out raw_enhanced.mp4

    # Настроить силу шумоподавления/резкости под конкретное видео
    python enhance.py --in raw.mp4 --out raw_enhanced.mp4 --denoise strong --sharpen light

    # Честный апскейл через Real-ESRGAN (нужен установленный video2x и GPU
    # с поддержкой Vulkan) — заметно медленнее, но реально увеличивает
    # детализацию, а не просто "мылит поменьше"
    python enhance.py --in raw.mp4 --out raw_enhanced.mp4 --upscale 2
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Пресеты силы шумоподавления/резкости — подобраны эмпирически под типичную
# картинку с фронтальной камеры телефона/ноутбука при среднем/слабом свете.
DENOISE_PRESETS = {
    "off": None,
    "light": "hqdn3d=2:1.5:3:2",
    "medium": "hqdn3d=4:3:6:4",
    "strong": "hqdn3d=8:6:8:6",
}

SHARPEN_PRESETS = {
    "off": None,
    "light": "unsharp=5:5:0.5:5:5:0.0",
    "medium": "unsharp=5:5:1.0:5:5:0.0",
    "strong": "unsharp=5:5:1.5:5:5:0.0",
}


def build_filter_chain(denoise: str, sharpen: str, brightness: float, contrast: float, saturation: float) -> str:
    parts = []
    if DENOISE_PRESETS.get(denoise):
        parts.append(DENOISE_PRESETS[denoise])
    # Небольшая коррекция экспозиции/контраста/насыщенности — компенсирует
    # типичную для слабых фронтальных камер плоскую, чуть тёмную картинку.
    if brightness != 0.0 or contrast != 1.0 or saturation != 1.0:
        parts.append(f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}")
    if SHARPEN_PRESETS.get(sharpen):
        parts.append(SHARPEN_PRESETS[sharpen])
    return ",".join(parts)


def run_ffmpeg_enhance(src: Path, out: Path, filter_chain: str) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if filter_chain:
        cmd += ["-vf", filter_chain]
    cmd += [
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def run_upscale(src: Path, out: Path, factor: int) -> None:
    """Апскейл через Video2X (CLI-обёртка над Real-ESRGAN). Требует, чтобы
    video2x был установлен отдельно (см. docs/setup.md) — это тяжёлая,
    необязательная зависимость, поэтому проверяем наличие явно и даём
    понятную инструкцию, если её нет, вместо непонятной ошибки."""
    binary = shutil.which("video2x")
    if not binary:
        sys.exit(
            "Не найден video2x в PATH. Это отдельный, необязательный инструмент "
            "для честного апскейла (см. docs/setup.md, раздел «Апскейл видео»). "
            "Без него доступно обычное улучшение (шум/резкость/экспозиция) — "
            "просто убери флаг --upscale."
        )
    subprocess.run(
        [binary, "-i", str(src), "-o", str(out),
         "-p", "realesrgan", "-s", str(factor)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--denoise", choices=DENOISE_PRESETS.keys(), default="medium",
                     help="сила шумоподавления (по умолчанию medium, off — выключить)")
    ap.add_argument("--sharpen", choices=SHARPEN_PRESETS.keys(), default="light",
                     help="сила резкости (по умолчанию light, off — выключить)")
    ap.add_argument("--brightness", type=float, default=0.03, help="сдвиг яркости, -1..1 (по умолчанию 0.03)")
    ap.add_argument("--contrast", type=float, default=1.05, help="контраст, множитель (по умолчанию 1.05)")
    ap.add_argument("--saturation", type=float, default=1.05, help="насыщенность, множитель (по умолчанию 1.05)")
    ap.add_argument("--upscale", type=int, choices=[2, 4], default=None,
                     help="во сколько раз честно увеличить разрешение через Real-ESRGAN "
                          "(нужен установленный video2x и GPU с Vulkan); "
                          "выполняется ДО шумоподавления/резкости")
    args = ap.parse_args()

    src = Path(args.inp)
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")
    out = Path(args.out)

    working = src
    tmp_upscaled = None
    if args.upscale:
        tmp_upscaled = out.with_name(out.stem + "_upscaled_tmp.mp4")
        run_upscale(src, tmp_upscaled, args.upscale)
        working = tmp_upscaled

    filter_chain = build_filter_chain(args.denoise, args.sharpen, args.brightness, args.contrast, args.saturation)
    if not filter_chain:
        # Нечего применять — апскейл (если был) уже дал нужный файл, иначе просто копируем.
        if working != src:
            working.rename(out)
        else:
            shutil.copyfile(src, out)
    else:
        run_ffmpeg_enhance(working, out, filter_chain)
        if tmp_upscaled and tmp_upscaled.exists():
            tmp_upscaled.unlink()

    print(f"OK: {out} — денойз={args.denoise}, резкость={args.sharpen}"
          + (f", апскейл x{args.upscale}" if args.upscale else ""))


if __name__ == "__main__":
    main()
