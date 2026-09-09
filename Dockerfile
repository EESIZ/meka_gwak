# MEKA 곽윤직 — 문체 측정·서식 대조 도구 이미지
# 사용: docker run --rm -v "$PWD:/work" ghcr.io/eesiz/meka_gwak style check draft.txt --domain civil --document-type judgment
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/EESIZ/meka_gwak" \
      org.opencontainers.image.description="MEKA 곽윤직: 한국 법률 실무 문체 측정(style_check)·서식 대조(format_check) 도구" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

WORKDIR /skill
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY SKILL.md LICENSE README.md ./
COPY data ./data
COPY references ./references
COPY scripts ./scripts
COPY sources ./sources
COPY tests ./tests

# meka style ... | meka format ... | meka test
RUN printf '%s\n' '#!/bin/sh' 'cmd="$1"; [ $# -gt 0 ] && shift' \
    'case "$cmd" in' \
    '  style)  exec python /skill/scripts/style_check.py "$@" ;;' \
    '  format) exec python /skill/scripts/format_check.py "$@" ;;' \
    '  test)   cd /skill && exec python -m unittest discover -s tests -v ;;' \
    '  *) echo "usage: meka style|format|test [args...]" >&2' \
    '     echo "  style  check <text> --domain civil|criminal|administrative --document-type <type> [--before <text>] [--output <json>]" >&2' \
    '     echo "  style  examples --domain <domain> --document-type <type> [--query <words>] [--pattern P01] [--limit N]" >&2' \
    '     echo "  format <final> --body <text> --form <json> [--attachments <json>] --output <json>" >&2' \
    '     exit 2 ;;' \
    'esac' > /usr/local/bin/meka && chmod +x /usr/local/bin/meka

# 사용자 작업 폴더를 /work에 마운트한다. 결과 파일은 스킬 폴더 밖(/work)에 저장된다.
WORKDIR /work
ENTRYPOINT ["meka"]
CMD []
