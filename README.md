# 🎵 Alice Spotify & AirPlay Lossless Bridge

Беспроводной стриминг **Spotify Connect** и **Apple AirPlay** на любую **Яндекс Станцию** (с Алисой) по локальной сети в оригинальном качестве **Lossless WAV 1411.2 kbps (bit-perfect)**.

---

## 🛠️ Что нужно для работы

1. **Подписка Spotify Premium**:
   * Для работы Spotify Connect на внешних аудиоустройствах (Spotify eSDK / Soloist) компания Spotify на уровне протокола требует активную подписку **Spotify Premium** (бесплатные аккаунты Connect на стороннем железе не поддерживаются).
   * Для воспроизведения через **Apple AirPlay** никакие подписки не нужны — передается любой звук с iPhone, iPad или Mac.
2. **Яндекс Станция**:
   * Любая модель (Станция 1/2, Макс, Миди, Мини 1/2, Лайт 1/2, ТВ Станции), подключенная к домашней Wi-Fi сети.
3. **Сервер или роутер (системные требования)**:
   * **Вариант А: ПК / Сервер / Raspberry Pi (Ubuntu / Debian / Raspberry Pi OS)**:
     * Свободное место на диске: от **500 МБ** (для пакетов PulseAudio, Shairport-Sync и Python-библиотек).
     * Оперативная память: от **256–512 МБ** (весь аудио-стек в работе потребляет всего ~**150 МБ** RAM).
   * **Вариант Б: Роутер с OpenWrt (x86_64 или aarch64)**:
     * USB-порт и флешка: от **2 ГБ** (архив Ubuntu rootfs занимает ~490 МБ, в распакованном виде в tmpfs — ~950 МБ).
     * Оперативная память роутера: от **512 МБ** (рекомендуется 1–2 ГБ RAM для комфортного монтирования tmpfs).

---

## 🔑 Как получить ключи и токены

Для работы моста нужны всего два параметра:

* **Яндекс `Session_id` (Cookie авторизации)**:
  1. Войдите в аккаунт на [yandex.ru](https://yandex.ru) в браузере с компьютера.
  2. Нажмите **F12** → вкладка **Application** (в Firefox — **Storage / Хранилище**) → слева **Cookies** → `https://yandex.ru`.
  3. Скопируйте значение строки **`Session_id`** (начинается с `3:...`).
* **Spotify Developer API Key (`spak_...`)**:
  * Специальный ключ для протокола Spotify eSDK. Интерактивный мастер `setup.py` автоматически предложит готовый рабочий ключ, либо можно использовать свой из [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
* **Фиксация статического IP Станции**:
  * В веб-интерфейсе роутера (**DHCP** → **Static Leases**) обязательно закрепите IP-адрес Станции по её MAC-адресу (например, `192.168.1.102`), чтобы колонка не меняла адрес при перезагрузке.
* **Device ID и Platform Станции**:
  * Вручную искать не нужно: мастер `setup.py` (или команда `python3 bridge.py --list-devices`) сам опросит облако Яндекса по вашему `Session_id` и покажет пронумерованный список ваших колонок.

---

## 🚀 Быстрый старт

### Вариант 1: Ubuntu / Debian / Raspberry Pi

1. **Установите системные зависимости**:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip pulseaudio pulseaudio-utils shairport-sync
   ```

2. **Клонируйте репозиторий и установите библиотеки**:
   ```bash
   git clone https://github.com/konchul/alice-spotify-bridge.git
   cd alice-spotify-bridge
   pip3 install -r requirements.txt
   ```

3. **Установите бинарник Soloist (Spotify Connect)**:
   ```bash
   sudo cp soloist /usr/local/bin/soloist
   sudo chmod +x /usr/local/bin/soloist
   ```

4. **Запустите интерактивный мастер настройки**:
   ```bash
   python3 setup.py
   ```
   Мастер запросит ключи, покажет список ваших Станций и сохранит готовый `config.json`.

5. **Включите автозапуск в systemd**:
   ```bash
   sudo cp systemd/*.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now soloist.service alice-spotify-bridge.service
   ```

---

### Вариант 2: OpenWrt (роутер с USB)

1. Подключите USB-флешку с файлами `bridge.py`, `setup.py`, `run_soloist.sh` и архивом `noble_rootfs.tar.gz`.
2. Скопируйте procd-скрипт и запустите службу:
   ```bash
   cp openwrt/spotify_bridge.init /etc/init.d/spotify_bridge
   chmod +x /etc/init.d/spotify_bridge
   /etc/init.d/spotify_bridge enable
   /etc/init.d/spotify_bridge start
   ```
3. Запустите первоначальную настройку:
   ```bash
   /root/setup.sh
   ```

---

## 💎 Как это работает и почему такой качественный звук

Большинство решений используют **Bluetooth** (сжатие кодеками SBC/AAC с задержкой 2 сек и срезом частот выше 16 кГц) или перекодирование в **MP3** (двойная потеря качества и нагрузка на CPU).

В этом проекте перекодирование **полностью отсутствует (Bit-Perfect Lossless 1411.2 kbps)**:

```mermaid
flowchart TD
    subgraph Sources["Источники звука"]
        SpotifyApp["Spotify Connect (Spotify Premium)"]
        AirPlaySrc["Apple AirPlay (iPhone / Mac / iPad)"]
    end

    subgraph Host["Сервер / Роутер"]
        Soloist["Soloist (Spotify eSDK)"]
        Shairport["shairport-sync (AirPlay)"]
        Pulse["PulseAudio (auto_null sink)"]
        Parec["parec (захват PCM s16le)"]
        Bridge["bridge.py (WAV Stream Server :8888)"]
    end

    subgraph Alice["Яндекс Станция"]
        Glagol["Glagol API (WSS :1961)"]
        Speaker["ЦАП и Динамик Станции"]
    end

    SpotifyApp -->|"Spotify Connect"| Soloist
    AirPlaySrc -->|"AirPlay"| Shairport
    Soloist -->|"PCM 44.1kHz 16-bit"| Pulse
    Shairport -->|"PCM 44.1kHz 16-bit"| Pulse
    Pulse --> Parec
    Parec -->|"s16le stereo"| Bridge
    Bridge -->|"GET /stream.wav?t=N (1411 kbps)"| Alice
    Bridge <-->|"WSS Glagol (громкость, метаданные)"| Glagol
    Glagol --> Speaker
```

### Преимущества звукового тракта:
* **Честный битрейт Audio CD**:
  $$\text{Битрейт} = 44\,100 \text{ Гц} \times 16 \text{ бит} \times 2 \text{ канала} = \mathbf{1411.2 \text{ кбит/с}}$$
* **Zero-Transcoding**: Звук из PulseAudio без перекодирования упаковывается в стандартный контейнер WAV (RIFF WAVE) и по локальной сети напрямую отдаётся аппаратному декодеру Станции.
* **Полный диапазон**: 20 Гц – 20 000 Гц без артефактов компрессии и динамический диапазон 96 дБ.
* **Токенизация потока (`?t=N`)**: при переключении треков URL получает новый токен, заставляя плеер Станции мгновенно сбрасывать буфер без застревания старого звука.
* **Изоляция клиентов по IP**: при переподключении колонки старые зависшие TCP-сокеты мгновенно вытесняются.
* **Двусторонняя громкость**: физические кнопки/колесо Станции плавно двигают ползунок в приложении Spotify, и наоборот (с 3-секундным анти-эхо фильтром).
* **Автоприоритет**: запуск AirPlay автоматически ставит Spotify на паузу, и наоборот.

---

## 📊 Сравнение методов передачи звука

| Параметр | Bluetooth на Станцию | MP3-мост | **Этот проект (Lossless WAV)** |
| :--- | :--- | :--- | :--- |
| **Формат аудио** | SBC / AAC (сжатие) | MP3 192–320 kbps (сжатие) | **PCM WAV (Lossless, без потерь)** |
| **Реальный битрейт** | ~250–320 kbps | 192–320 kbps | **1411.2 kbps (Bit-Perfect CD Quality)** |
| **Повторное сжатие** | Да (двойное) | Да (mp3lame) | **Нет (0% потерь качества)** |
| **Частотный срез** | Срезано выше 16–17 кГц | Срезано выше 18 кГц | **Полные 20 Гц – 20 000 Гц** |
| **Задержка старта** | 1.5 – 3.0 сек | 2.0 – 4.0 сек | **< 0.35 сек (Pre-roll буфер 500 мс)** |
| **Громкость со Станции** | ❌ Не синхронизирует Spotify | ❌ В одну сторону | **✅ Двусторонняя (кнопки Станции ⇄ Spotify)** |
| **Отображение обложек** | ❌ Нет | ❌ Только текст | **✅ Название, Артист и Обложка трека** |
| **Нагрузка на процессор** | Средняя | Высокая | **Минимальная (< 2% CPU)** |

---

## 📄 Лицензия

Проект распространяется под свободной лицензией **MIT License**. Подробнее см. в файле [LICENSE](LICENSE).
