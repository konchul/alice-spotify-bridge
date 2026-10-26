#!/bin/bash
export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

# Find binaries
SOLOIST_BIN="$(command -v soloist 2>/dev/null || echo "/usr/local/bin/soloist")"
PYTHON_BIN="$(command -v python3 2>/dev/null || echo "/usr/bin/python3")"

# Find configuration file
CONFIG_FILE="${CONFIG_PATH:-}"
if [ -z "$CONFIG_FILE" ]; then
    for c in "./config.json" "/root/config.json" "/mnt/usb/config.json" "/etc/alice-spotify-bridge/config.json"; do
        if [ -f "$c" ]; then
            CONFIG_FILE="$c"
            break
        fi
    done
fi

DATA_DIR="${SOLOIST_DATA:-/root/soloist_data}"
[ ! -d "$DATA_DIR" ] && [ -d "./soloist_data" ] && DATA_DIR="./soloist_data"

CACHE_DIR="${SOLOIST_CACHE:-/root/soloist_cache}"
[ ! -d "$CACHE_DIR" ] && [ -d "./soloist_cache" ] && CACHE_DIR="./soloist_cache"

mkdir -p "$DATA_DIR" "$CACHE_DIR"

NAME="Alice 27"
KEY=""

if [ -n "$CONFIG_FILE" ] && [ -f "$CONFIG_FILE" ]; then
    NAME=$("$PYTHON_BIN" -c "import json; print(json.load(open('$CONFIG_FILE')).get('spotify', {}).get('device_name', 'Alice 27'))" 2>/dev/null || echo "Alice 27")
    KEY=$("$PYTHON_BIN" -c "import json; print(json.load(open('$CONFIG_FILE')).get('spotify', {}).get('api_key', ''))" 2>/dev/null || echo "")
fi

if [ -z "$KEY" ]; then
    echo "❌ Ошибка: Spotify Developer API ключ не найден в config.json!" >&2
    echo "Запустите мастер настройки: python3 setup.py" >&2
    exit 1
fi

exec "$SOLOIST_BIN" -n "$NAME" -k "$KEY" -D "$DATA_DIR" -C "$CACHE_DIR" -w 127.0.0.1:9090 -v
