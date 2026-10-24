#!/usr/bin/env bash
set -euo pipefail

model="${WHISPER_MODEL:-small}"
language="${WHISPER_LANG:-en}"
beam_size="${WHISPER_BEAM_SIZE:-5}"
http_host="${WHISPER_HTTP_HOST:-127.0.0.1}"
http_port="${WHISPER_HTTP_PORT:-8910}"
wyoming_uri="${WYOMING_URI:-tcp://0.0.0.0:7891}"
model_url="${MODEL_BASE_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main}"
model_path="/models/ggml-${model}.bin"

mkdir -p /models
if [[ ! -s "$model_path" ]]; then
  temporary="$(mktemp "${model_path}.XXXXXX")"
  trap 'rm -f "$temporary"' EXIT
  wget -qO "$temporary" "${model_url}/ggml-${model}.bin"
  mv "$temporary" "$model_path"
  trap - EXIT
fi

/whisper.cpp/build/bin/whisper-server \
  -m "$model_path" \
  --host "$http_host" --port "$http_port" \
  -l "$language" -bs "$beam_size" --suppress-nst &

exec /opt/wyoming-venv/bin/python -m wyoming_whisper_api_client \
  --uri "$wyoming_uri" \
  --api "http://${http_host}:${http_port}/inference"
