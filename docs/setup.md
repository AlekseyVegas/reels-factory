# Установка

## Зависимости

- **ffmpeg / ffprobe** — резка, склейка, звук, субтитры.
- **Python 3.10+** — стандартная библиотека, дополнительных пакетов не требуется.
- **whisper.cpp** — офлайн-распознавание речи (движок `whisper-cli` + модель `ggml-*.bin`).

## whisper.cpp

Если под рукой нет готового бинарника, собрать из исходников:

```bash
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j --target whisper-cli
```

Бинарник появится в `build/bin/whisper-cli`.

### Модель

Скачать веса модели (один раз, файл большой):

```bash
mkdir -p ~/.whisper-models
curl -L -o ~/.whisper-models/ggml-medium.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin
```

**Про выбор модели:** `ggml-large-v3.bin` точнее, но требует ~3.5–4 ГБ оперативной памяти в моменте распознавания — на машинах/окружениях с ограниченной RAM (даже при большом объёме диска) процесс может быть аварийно завершён (OOM). `ggml-medium.bin` (~1.5 ГБ) даёт почти такое же качество на русском и требует заметно меньше памяти — стартовая рекомендация.

### Указать скрипту, где что лежит

```bash
export WHISPER_CLI_BIN=/путь/к/whisper-cli
export WHISPER_MODEL=~/.whisper-models/ggml-medium.bin
```

Либо передавать флагами `--whisper-bin` / `--model` в `transcribe.py`.

## Проверка

```bash
python tools/tighten.py --in test.mp4 --out /tmp/tight.mp4
python tools/transcribe.py --in /tmp/tight.mp4 --out /tmp/words.json
python tools/captions.py --in /tmp/tight.mp4 --words /tmp/words.json --out /tmp/final.mp4
```

Если на выходе `/tmp/final.mp4` открывается и субтитры совпадают по смыслу и времени с речью — всё установлено верно.
