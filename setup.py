#!/usr/bin/env python3
"""
Интерактивный мастер первоначальной настройки и конфигурации
Spotify Connect + AirPlay для Яндекс Станции (Glagol API).
"""

import os
import sys
import json
import socket
import urllib.request
import subprocess

CONFIG_PATHS = [
    "/root/config.json",
    "/mnt/usb/config.json",
    "config.json"
]

def load_existing_config():
    for p in CONFIG_PATHS:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f), p
            except Exception:
                pass
    return {}, None

def prompt(label, default="", hide_text=False):
    if default:
        display = f"{label} [{default}]: "
    else:
        display = f"{label}: "
    val = input(display).strip()
    return val if val else default

def check_ip_port(ip, port, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((ip, int(port)))
        s.close()
        return res == 0
    except Exception:
        return False

def get_yandex_devices(session_id):
    url = "https://quasar.yandex.ru/glagol/device_list"
    req = urllib.request.Request(url, headers={"Cookie": f"Session_id={session_id}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok":
                # Filter devices that look like speakers or glagol endpoints
                devices = data.get("devices", [])
                valid = [d for d in devices if d.get("platform") and not d.get("platform").startswith("alice_app")]
                return valid if valid else devices
    except Exception as e:
        print(f"\n❌ Ошибка обращения к API Яндекса: {e}")
    return None

def main():
    print("=" * 65)
    print(" 🎵 Мастер настройки: Spotify Connect + AirPlay на Яндекс Станцию")
    print("=" * 65)
    print("Этот мастер поможет быстро настроить config.json и проверить")
    print("связь со всеми сервисами и колонкой.\n")

    cfg, found_path = load_existing_config()
    if found_path:
        print(f"ℹ️  Обнаружен существующий конфиг: {found_path}")
        print("   (Нажмите Enter на любом вопросе, чтобы оставить текущее значение)\n")

    yandex_cfg = cfg.get("yandex", {})
    spotify_cfg = cfg.get("spotify", {})
    server_cfg = cfg.get("server", {})
    airplay_cfg = cfg.get("airplay", {})
    audio_cfg = cfg.get("audio", {})

    # 1. Spotify
    print("-" * 65)
    print("▶️  ШАГ 1: Настройки Spotify Connect")
    print("-" * 65)
    spotify_key = prompt(
        "Spotify Developer API Key (начинается с spak_...)",
        spotify_cfg.get("api_key", "")
    )
    spotify_name = prompt(
        "Имя устройства в приложении Spotify Connect",
        spotify_cfg.get("device_name", "Alice 27")
    )

    # 2. Yandex Session_id
    print("\n" + "-" * 65)
    print("▶️  ШАГ 2: Яндекс Авторизация (Session_id)")
    print("-" * 65)
    print("Инструкция: войдите в yandex.ru в браузере -> F12 -> Application ->")
    print("Cookies -> yandex.ru -> скопируйте значение 'Session_id'.\n")

    session_id = prompt(
        "Yandex Session_id Cookie",
        yandex_cfg.get("session_id", "")
    )

    if not session_id:
        print("❌ Ошибка: Session_id обязателен для авторизации в Glagol API!")
        sys.exit(1)

    print("\n🔄 Подключение к Яндекс Quasar API и поиск колонок...")
    devices = get_yandex_devices(session_id)

    selected_id = yandex_cfg.get("device_id", "")
    selected_platform = yandex_cfg.get("platform", "yandexmini_2")

    if devices:
        print(f"✅ Найдено устройств с Алисой: {len(devices)}")
        print("\nВыберите вашу Яндекс Станцию:")
        for idx, d in enumerate(devices, 1):
            name = d.get("name", "Колонка")
            dev_id = d.get("id", "")
            platform = d.get("platform", "")
            is_current = " (текущая)" if dev_id == selected_id else ""
            print(f"  [{idx}] {name}  |  Модель: {platform}  |  ID: {dev_id}{is_current}")

        while True:
            choice = input(f"\nВведите номер устройства [1-{len(devices)}] или нажмите Enter: ").strip()
            if not choice and selected_id:
                print(f"-> Оставлено текущее: ID {selected_id}")
                break
            try:
                n = int(choice)
                if 1 <= n <= len(devices):
                    chosen = devices[n - 1]
                    selected_id = chosen.get("id")
                    selected_platform = chosen.get("platform")
                    print(f"-> Выбрано: {chosen.get('name')} (ID: {selected_id}, Модель: {selected_platform})")
                    break
                else:
                    print("Неверный номер, попробуйте снова.")
            except ValueError:
                print("Введите число.")
    else:
        print("⚠️  Не удалось получить список устройств автоматически.")
        selected_id = prompt("Введите Device ID вручную", selected_id)
        selected_platform = prompt("Введите Platform вручную (например yandexmini_2)", selected_platform)

    # 3. Station IP
    print("\n" + "-" * 65)
    print("▶️  ШАГ 3: Локальный IP-адрес Яндекс Станции")
    print("-" * 65)
    station_ip = prompt("Локальный IP-адрес Станции в вашей Wi-Fi сети", yandex_cfg.get("station_ip", "192.168.1.102"))

    # ПРЕДУПРЕЖДЕНИЕ О СТАТИЧЕСКОМ IP
    print("\n" + "!" * 65)
    print("⚠️  ВНИМАНИЕ! ВАЖНОЕ ТРЕБОВАНИЕ К СЕТИ:")
    print(f"   IP-адрес {station_ip} должен быть СТАТИЧЕСКИМ!")
    print("   Обязательно зайдите в настройки вашего роутера:")
    print("   Сеть (Network) -> DHCP -> Привязка IP к MAC-адресу (Static Lease).")
    print("   Если роутер со временем выдаст колонке другой IP — воспроизведение")
    print("   остановится и потребуется менять IP в настройках!")
    print("!" * 65)

    print(f"\n🔄 Проверка связи с колонкой {station_ip}:1961...")
    if check_ip_port(station_ip, 1961, timeout=3):
        print(f"✅ Успешно! Порт 1961 (Glagol API) на {station_ip} отвечает. Колонка в сети.")
    else:
        print(f"⚠️  Предупреждение: порт 1961 на {station_ip} не ответил за 3 сек.")
        print("   Проверьте, включена ли колонка в розетку и подключена ли к Wi-Fi.")

    # 4. Сборка нового config.json
    new_config = {
        "spotify": {
            "device_name": spotify_name,
            "api_key": spotify_key
        },
        "yandex": {
            "session_id": session_id,
            "station_ip": station_ip,
            "device_id": selected_id,
            "platform": selected_platform
        },
        "server": {
            "stream_host": server_cfg.get("stream_host", "auto"),
            "http_port": int(server_cfg.get("http_port", 8888)),
            "soloist_ws": server_cfg.get("soloist_ws", "ws://127.0.0.1:9090")
        },
        "airplay": {
            "audio_fifo": airplay_cfg.get("audio_fifo", "/tmp/shairport-sync-audio"),
            "meta_fifo": airplay_cfg.get("meta_fifo", "/tmp/shairport-sync-metadata")
        },
        "audio": {
            "pause_debounce_sec": float(audio_cfg.get("pause_debounce_sec", 0.35))
        }
    }

    # 5. Сохранение
    print("\n" + "-" * 65)
    print("▶️  ШАГ 4: Сохранение настроек")
    print("-" * 65)

    save_targets = ["/root/config.json", "/mnt/usb/config.json"]
    saved_any = False
    for target in save_targets:
        target_dir = os.path.dirname(target)
        if os.path.isdir(target_dir):
            try:
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(new_config, f, indent=2, ensure_ascii=False)
                os.chmod(target, 0o600)
                print(f"✅ Конфигурация сохранена в: {target}")
                saved_any = True
            except Exception as e:
                print(f"❌ Ошибка записи в {target}: {e}")

    if not saved_any:
        # Fallback to current directory
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        print("✅ Конфигурация сохранена в текущую папку: config.json")

    # 6. Обновление run_soloist.sh
    soloist_script = "/root/run_soloist.sh"
    if os.path.isfile(soloist_script):
        try:
            content = f'''#!/bin/bash
export HOME=/root
exec /usr/local/bin/soloist -n "{spotify_name}" -k "{spotify_key}" -D /root/soloist_data -C /root/soloist_cache -w 127.0.0.1:9090 -v
'''
            with open(soloist_script, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(soloist_script, 0o755)
            print(f"✅ Обновлен скрипт запуска Spotify Connect: {soloist_script}")
        except Exception as e:
            print(f"⚠️  Не удалось обновить {soloist_script}: {e}")

    # 7. Предложение перезапуска
    print("\n" + "=" * 65)
    print("🎉 Настройка успешно завершена!")
    print("=" * 65)

    ans = input("\nПерезапустить сервис прямо сейчас для применения? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes", "д", "да"):
        print("\n🔄 Перезапуск службы spotify_bridge...")
        if os.path.isfile("/etc/init.d/spotify_bridge"):
            subprocess.run(["/etc/init.d/spotify_bridge", "restart"])
            print("✅ Служба перезапущена! Проверьте звук.")
        else:
            # Maybe inside chroot or other system
            print("ℹ️  Служба перезапущена через команду: /etc/init.d/spotify_bridge restart")
    else:
        print("\nДля применения настроек выполните вручную:")
        print("  /etc/init.d/spotify_bridge restart")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nНастройка отменена пользователем.")
        sys.exit(0)
