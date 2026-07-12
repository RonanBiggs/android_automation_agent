#!/usr/bin/env bash

set -u

TEXT_MODEL="hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q5_K_M"
VISION_MODEL="llama3.2-vision:11b"

LOG_DIR="$HOME/ai_service_logs"
mkdir -p "$LOG_DIR"

OLLAMA_LOG="$LOG_DIR/ollama_serve.log"
TEXT_LOG="$LOG_DIR/qwen_coder.log"
VISION_LOG="$LOG_DIR/llama_vision.log"

PIDS=()

cleanup() {
    echo
    echo "Stopping AI services..."

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping PID $pid"
            kill "$pid" 2>/dev/null
        fi
    done

    sleep 2

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Force stopping PID $pid"
            kill -9 "$pid" 2>/dev/null
        fi
    done

    echo "Done."
    exit 0
}

trap cleanup INT TERM

echo "Starting Ollama server..."
ollama serve > "$OLLAMA_LOG" 2>&1 &
PIDS+=("$!")

sleep 3

echo "Loading text model..."
ollama run "$TEXT_MODEL" > "$TEXT_LOG" 2>&1 &
PIDS+=("$!")

sleep 2

echo "Loading vision model..."
ollama run "$VISION_MODEL" > "$VISION_LOG" 2>&1 &
PIDS+=("$!")

echo
echo "AI services started."
echo
echo "Logs:"
echo "  Ollama server: $OLLAMA_LOG"
echo "  Text model:    $TEXT_LOG"
echo "  Vision model:  $VISION_LOG"
echo
echo "Press q to quit AI services."

while true; do
    read -rsn1 key
    if [[ "$key" == "q" ]]; then
        cleanup
    fi
done
