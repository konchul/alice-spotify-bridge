# 📖 Инструкция по настройке и конфигурации (Spotify Connect + AirPlay → Яндекс Станция)

Для быстрой первоначальной настройки или смены колонки создан **интерактивный мастер настройки**:
```bash
/root/setup.sh
# или внутри chroot/системы: python3 setup.py
```
Мастер пошагово запросит ключи, сам найдет все ваши колонки в аккаунте Яндекса, проверит связь по сети и предупредит о фиксации статического IP-адреса.

> [!NOTE]
> Для воспроизведения через **Spotify Connect** требуется активная подписка **Spotify Premium** (официальное ограничение протокола Spotify Connect). Для стриминга через **Apple AirPlay** никакие подписки не нужны.

---

## 1. Структура `config.json`

Файл конфигурации хранится в корне проекта (`/root/config.json` или `/mnt/usb/config.json`). Шаблон без секретов сохранён в `config.example.json`.

```json
{
  "yandex": {
    "session_id": "YOUR_YANDEX_SESSION_ID",
    "station_ip": "192.168.1.100",
    "device_id": "YOUR_DEVICE_ID",
    "platform": "yandexmini_2"
  },
  "server": {
    "stream_host": "auto",
    "http_port": 8888,
    "soloist_ws": "ws://127.0.0.1:9090"
  },
  "airplay": {
    "audio_fifo": "/tmp/shairport-sync-audio",
    "meta_fifo": "/tmp/shairport-sync-metadata"
  },
  "audio": {
    "pause_debounce_sec": 0.35
  }
}
```

### Описание параметров:
* `yandex.session_id` — Cookie авторизации Яндекс Аккаунта. Нужен для получения локального токена Glagol API.
* `yandex.station_ip` — Локальный IP-адрес колонки в вашей Wi-Fi сети.
* `yandex.device_id` — Уникальный аппаратный идентификатор колонки.
* `yandex.platform` — Модель колонки (`yandexmini_2`, `yandexstation`, `yandexstation_2`, `yandexmicro` и т.д.).
* `server.stream_host` — IP-адрес роутера/сервера, с которого колонка забирает WAV-поток. Если указано `"auto"`, скрипт автоматически определит свой IP в сторону колонки.
* `server.http_port` — Порт локального HTTP WAV-сервера (по умолчанию `8888`).
* `server.soloist_ws` — Адрес WebSocket Soloist (Spotify Connect).
* `airplay.audio_fifo` и `meta_fifo` — Именованные каналы (FIFO) для приема PCM звука и названий треков от `shairport-sync`.

---

## 2. Как получить `session_id` (Яндекс)

Cookie `Session_id` выдаётся Яндексом при входе в аккаунт и обычно действует от нескольких месяцев до года (пока вы явно не нажмёте «Выйти»).

1. Откройте браузер (Chrome / Яндекс Браузер / Firefox) на компьютере.
2. Перейдите на сайт [yandex.ru](https://yandex.ru) или [quasar.yandex.ru](https://quasar.yandex.ru) и убедитесь, что вы авторизованы в аккаунте, к которому привязана колонка.
3. Нажмите клавишу **F12** (или `Ctrl + Shift + I`), чтобы открыть Инструменты разработчика.
4. Перейдите на вкладку **Application** (в Chrome/Яндекс) или **Хранилище (Storage)** (в Firefox).
5. В левом меню раскройте **Cookies** → выберите `https://yandex.ru` (или `.yandex.ru`).
6. В таблице найдите строку с именем **`Session_id`**.
7. Дважды кликните по значению и скопируйте всю длинную строку (начинается обычно с цифры, например `3:17...`).
8. Вставьте скопированное значение в поле `"session_id"` вашего `config.json`.

---

## 3. Как узнать `device_id` и `platform` колонки

После того как вы вставили `session_id` в `config.json`, узнать ID и платформу любой вашей колонки можно за 2 секунды.

### Способ 1: Встроенная команда автоматического поиска (Рекомендуется)
Выполните команду на устройстве:
```bash
python3 bridge.py --list-devices
```
*(Или в chroot на роутере: `chroot /tmp/noble python3 /root/bridge.py --list-devices`)*

Скрипт сам обратится к API Яндекса и выведет список всех ваших устройств:
```text
=== YANDEX ALICE DEVICES FOUND ===
Name:     Living Room
ID:       EXAMPLE_DEVICE_ID_1
Platform: yandexmini_2
-----------------------------------
Name:     Kitchen
ID:       EXAMPLE_DEVICE_ID_2
Platform: yandexstation_2
-----------------------------------
```
Просто скопируйте `ID` и `Platform` нужной колонки в `config.json`.

### Способ 2: Через браузер
Если скрипт ещё не запущен, откройте в том же браузере страницу:
👉 **https://quasar.yandex.ru/glagol/device_list**

Вам вернется JSON со всеми привязанными Станциями, где для каждой указаны:
* `"id"` → значение для `device_id`
* `"platform"` → значение для `platform`
* `"name"` → название комнаты/колонки

---

## 4. Как узнать и закрепить IP-адрес Станции (`station_ip`)

Яндекс Станция общается с бриджем напрямую по локальной сети через порт `1961` (протокол Glagol). Чтобы колонка не теряла связь при перезагрузке роутера, её IP должен быть статическим.

1. **Как узнать текущий IP**:
   * В приложении **«Дом с Алисой»**: выберите колонку → Настройки (шестерёнка) → Информация об устройстве → IP-адрес.
   * Либо в веб-интерфейсе роутера (вкладка **Status** → **Overview** / **DHCP Leases**) найдите устройство с именем производителя (например, *Yandex* или по MAC-адресу).
2. **Как зафиксировать IP (Static Lease)**:
   * В веб-интерфейсе OpenWrt: перейдите в **Network** → **DHCP and DNS** → раздел **Static Leases**.
   * Нажмите **Add**, выберите MAC-адрес Станции и задайте постоянный IP (например, `192.168.1.102`).
   * Сохраните и примените настройки (**Save & Apply**).
3. Пропишите этот IP в `config.json` в поле `"station_ip"`.

---

## 5. Как переключить звук на другую колонку

Если в доме несколько Яндекс Станций и вы хотите переключить стриминг на другую:
1. Запустите `python3 bridge.py --list-devices`, чтобы увидеть ID и платформу второй колонки.
2. В файле `/mnt/usb/config.json` (или `config.json`) измените 3 строчки:
   * `"station_ip"`: новый IP адрес
   * `"device_id"`: новый ID
   * `"platform"`: платформа новой колонки
3. Перезапустите сервис:
   ```bash
   /etc/init.d/spotify_bridge restart
   ```
Всё! Spotify Connect и AirPlay мгновенно переключатся на новую Станцию.

---

## 6. Примечания по безопасности для GitHub

* **Никогда не коммитьте `config.json` в репозиторий!**
* Добавьте файл в `.gitignore`:
  ```text
  config.json
  *.pyc
  __pycache__/
  soloist_cache/
  soloist_data/
  ```
* В репозитории храните только файл-образец `config.example.json`.
