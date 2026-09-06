# Установка

## Зависимости

- **ffmpeg / ffprobe** — резка, склейка, звук, субтитры.
- **Python 3.10+** — плюс библиотека `Pillow` (`pip install pillow`), нужна для автоподбора размера субтитров.
- **whisper.cpp** — офлайн-распознавание речи (движок `whisper-cli` + модель `ggml-*.bin`).
- **Шрифт для субтитров** — см. раздел ниже.

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

## Шрифт для субтитров

`captions.py` по умолчанию ищет шрифт `fonts/Montserrat-Black.otf` (рядом с папкой `tools/`, семейство `Montserrat Black`) — свободный шрифт (лицензия SIL OFL 1.1) с полной поддержкой кириллицы. В самом репозитории бинарный файл шрифта не хранится — скачай его один раз из канонического репозитория автора шрифта:

```bash
mkdir -p fonts
curl -L -o fonts/Montserrat-Black.otf \
  "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/otf/Montserrat-Black.otf"
```

Если файл по этой ссылке недоступен, найди актуальную ссылку прямо в репозитории [github.com/JulietaUla/Montserrat](https://github.com/JulietaUla/Montserrat) (папка `fonts/otf/`) либо на странице [fonts.google.com/specimen/Montserrat](https://fonts.google.com/specimen/Montserrat) → «Download family» → взять файл веса Black (900).

После скачивания можно проверить, как система видит имя шрифта (`fc-scan fonts/Montserrat-Black.otf | grep fullname`) — если оно отличается от `Montserrat Black`, передай реальное имя через флаг `--font` у `captions.py`.

Хочешь другой шрифт/стиль — подойдёт любой `.ttf`/`.otf` с поддержкой кириллицы, просто укажи путь через `--font-file` и имя семейства через `--font`.

## Проверка

```bash
python tools/tighten.py --in test.mp4 --out /tmp/tight.mp4
python tools/transcribe.py --in /tmp/tight.mp4 --out /tmp/words.json
python tools/captions.py --in /tmp/tight.mp4 --words /tmp/words.json --out /tmp/final.mp4
```

Если на выходе `/tmp/final.mp4` открывается и субтитры совпадают по смыслу и времени с речью — всё установлено верно.
