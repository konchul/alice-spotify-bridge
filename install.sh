#!/bin/bash
# ==============================================================================
#  Alice Spotify & AirPlay Lossless Bridge - Universal One-Line Installer
#  GitHub: https://github.com/konchul/alice-spotify-bridge
# ==============================================================================

set -e

# Reconnect stdin to terminal if script was piped via curl | bash
if [ -t 0 ]; then
    INTERACTIVE=1
else
    if [ -e /dev/tty ]; then
        exec < /dev/tty
        INTERACTIVE=1
    else
        INTERACTIVE=0
    fi
fi

echo "=================================================================="
echo " 🎵 Установка: Alice Spotify & AirPlay Lossless Bridge"
echo "=================================================================="

# 1. Определение операционной системы
if [ -f /etc/openwrt_release ] || grep -qi "openwrt" /etc/os-release 2>/dev/null; then
    OS_TYPE="openwrt"
elif command -v apt-get >/dev/null 2>&1; then
    OS_TYPE="debian"
else
    OS_TYPE="generic"
fi

echo "Обнаружена система: $OS_TYPE"

# ------------------------------------------------------------------------------
# СЦЕНАРИЙ 1: Ubuntu / Debian / Raspberry Pi OS
# ------------------------------------------------------------------------------
if [ "$OS_TYPE" = "debian" ]; then
    # Требуем root или sudo
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Ошибка: для установки пакетов запустите скрипт через sudo:"
        echo "   curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/install.sh | sudo bash"
        exit 1
    fi

    echo -e "\n📦 1/5. Установка системных пакетов (PulseAudio, Shairport-Sync, Python3)..."
    apt-get update -y
    apt-get install -y git python3 python3-pip pulseaudio pulseaudio-utils shairport-sync curl wget

    INSTALL_DIR="/opt/alice-spotify-bridge"
    echo -e "\n📥 2/5. Загрузка репозитория в $INSTALL_DIR..."
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo "Обновление существующего репозитория..."
        git -C "$INSTALL_DIR" pull
    else
        rm -rf "$INSTALL_DIR"
        git clone https://github.com/konchul/alice-spotify-bridge.git "$INSTALL_DIR"
    fi

    echo -e "\n🐍 3/5. Установка Python-зависимостей..."
    pip3 install --break-system-packages -r "$INSTALL_DIR/requirements.txt" 2>/dev/null || \
    pip3 install -r "$INSTALL_DIR/requirements.txt"

    echo -e "\n⚡️ 4/5. Оптимизация PulseAudio (снижение RAM с 750 МБ до 8 МБ)..."
    if [ -d /etc/pulse ]; then
        [ -f /etc/pulse/default.pa ] && [ ! -f /etc/pulse/default.pa.orig ] && cp /etc/pulse/default.pa /etc/pulse/default.pa.orig
        [ -f /etc/pulse/daemon.conf ] && [ ! -f /etc/pulse/daemon.conf.orig ] && cp /etc/pulse/daemon.conf /etc/pulse/daemon.conf.orig
        cp "$INSTALL_DIR/pulseaudio/default.pa" /etc/pulse/default.pa
        cp "$INSTALL_DIR/pulseaudio/daemon.conf" /etc/pulse/daemon.conf
        echo "Применен легковесный bit-perfect профиль PulseAudio."
    fi

    # Проверка бинарника soloist
    if ! command -v soloist >/dev/null 2>&1 && [ ! -f /usr/local/bin/soloist ]; then
        echo -e "\n⚠️  ВНИМАНИЕ: Бинарник Soloist (Spotify Connect eSDK) не найден в /usr/local/bin/soloist."
        echo "   Поместите бинарник soloist в /usr/local/bin/soloist и выполните chmod +x /usr/local/bin/soloist"
    fi

    echo -e "\n⚙️  5/5. Настройка служб systemd..."
    cp "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/
    systemctl daemon-reload

    echo -e "\n🎉 Установка завершена!"
    if [ "$INTERACTIVE" -eq 1 ]; then
        echo -e "\nЗапуск мастера настройки..."
        python3 "$INSTALL_DIR/setup.py"
    else
        echo "Для настройки запустите: python3 $INSTALL_DIR/setup.py"
    fi

    echo -e "\nДля запуска служб выполните:"
    echo "  sudo systemctl enable --now soloist.service alice-spotify-bridge.service"
    exit 0
fi

# ------------------------------------------------------------------------------
# СЦЕНАРИЙ 2: OpenWrt (роутер)
# ------------------------------------------------------------------------------
if [ "$OS_TYPE" = "openwrt" ]; then
    echo -e "\n📡 Настройка на роутере OpenWrt..."

    USB_DIR="/mnt/usb"
    if [ ! -d "$USB_DIR" ]; then
        # Ищем первый смонтированный диск в /mnt/
        FIRST_MOUNT=$(mount | grep "/mnt/" | head -n1 | awk '{print $3}')
        if [ -n "$FIRST_MOUNT" ]; then
            USB_DIR="$FIRST_MOUNT"
        fi
    fi

    echo "Целевой каталог на накопителе: $USB_DIR"
    mkdir -p "$USB_DIR" "$USB_DIR/pulseaudio"

    echo "Загрузка компонентов моста..."
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/bridge.py -o "$USB_DIR/bridge.py"
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/setup.py -o "$USB_DIR/setup.py"
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/run_soloist.sh -o "$USB_DIR/run_soloist.sh"
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/pulseaudio/default.pa -o "$USB_DIR/pulseaudio/default.pa"
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/pulseaudio/daemon.conf -o "$USB_DIR/pulseaudio/daemon.conf"
    chmod +x "$USB_DIR/setup.py" "$USB_DIR/run_soloist.sh"

    # Применение PulseAudio профиля в chroot если доступен
    if [ -d "/tmp/noble/etc/pulse" ]; then
        cp "$USB_DIR/pulseaudio/default.pa" "/tmp/noble/etc/pulse/default.pa" 2>/dev/null || true
        cp "$USB_DIR/pulseaudio/daemon.conf" "/tmp/noble/etc/pulse/daemon.conf" 2>/dev/null || true
    fi

    echo "Установка службы OpenWrt procd..."
    curl -sSL https://raw.githubusercontent.com/konchul/alice-spotify-bridge/main/openwrt/spotify_bridge.init -o /etc/init.d/spotify_bridge
    chmod +x /etc/init.d/spotify_bridge
    /etc/init.d/spotify_bridge enable

    echo -e '#!/bin/sh\nexec chroot /tmp/noble python3 /root/setup.py "$@"' > /root/setup.sh
    chmod +x /root/setup.sh

    echo -e "\n🎉 Компоненты OpenWrt установлены!"
    echo "Запуск службы: /etc/init.d/spotify_bridge start"
    echo "Мастер настройки: /root/setup.sh"

    /etc/init.d/spotify_bridge start 2>/dev/null || true

    if [ "$INTERACTIVE" -eq 1 ]; then
        sleep 2
        /root/setup.sh
    fi
    exit 0
fi

# ------------------------------------------------------------------------------
# СЦЕНАРИЙ 3: Другие Linux-дистрибутивы
# ------------------------------------------------------------------------------
echo "Для вашей системы выполните установку вручную по инструкции из README."
exit 1
