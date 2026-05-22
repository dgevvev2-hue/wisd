# wisd

VPN-панель и VLESS-туннель для x86_64 Linux VPS.

Состоит из:

- `site/` — веб-интерфейс (HTML/JS) + sh-CGI бэкенд под `bash` и `fcgiwrap`.
- `deploy/` — установщик и шаблоны: `nginx`, `systemd`, конфиг Xray.
- `proxy_manager/` — Android-приложение (Flutter), клиент-маршрутизатор по приложениям.

## Что это делает

- Поднимает на VPS **Xray-сервер**: VLESS inbound на :443 (TLS/Reality), плюс локальные SOCKS5 (`:1080`) и HTTP (`:1081`).
- Веб-панель умеет:
    - Включать/выключать туннель.
    - Переключать режим **Direct** (трафик уходит с IP самого VPS) ↔ **Tunnel** (трафик уходит через выбранный upstream VLESS-узел).
    - Загружать VLESS-подписки (по URL или ручной вставкой), парсить, сохранять. Подписки **не обновляются автоматически**.
    - Управлять маршрутами (какие домены/IP идут через туннель, какие — direct).
    - Показывать трафик и состояние процесса.

## Быстрая установка (Debian/Ubuntu)

```bash
git clone https://github.com/dgevvev2-hue/wisd.git
cd wisd
sudo bash deploy/install.sh
```

Скрипт:

1. Ставит `nginx`, `fcgiwrap`, `xray`, `jq`, `curl`.
2. Копирует `site/` в `/var/www/wisd/`.
3. Кладёт `nginx`-конфиг и `systemd`-юнит для Xray.
4. Генерирует пару ключей VLESS-Reality и UUID клиента.
5. Открывает порты `:80` (web), `:443` (VLESS).

После установки веб-панель доступна на `http://<IP-VPS>/`, готовая VLESS-ссылка лежит в `/var/lib/wisd/client_url.txt`.

## Архитектура

```
браузер ──► nginx :80 ──► HTML/JS (site/)
                     └─► fcgiwrap → bash CGI (site/cgi-bin/*.cgi)
                                     │
                                     ▼
                       /etc/wisd/xray.json (генерируется CGI)
                                     │
                                     ▼
            systemd: wisd-xray.service ──► xray
                                            ├── inbound  :443 VLESS-Reality (для клиентов)
                                            ├── inbound  :1080 SOCKS5  (локально, 127.0.0.1)
                                            ├── inbound  :1081 HTTP    (локально, 127.0.0.1)
                                            └── outbound:
                                                 ├── freedom (Direct, выход с IP VPS)
                                                 └── vless   (Tunnel, через upstream)
```

## Структура состояния

Всё runtime-состояние — в `/var/lib/wisd/`:

- `subscriptions/index.json` — список подписок (id, name, url, addedAt).
- `subscriptions/<id>.json` — распаршенные узлы конкретной подписки.
- `nodes.json` — объединённый список всех узлов.
- `state` — текущее состояние (`up`/`down`).
- `mode` — `direct` или `tunnel`.
- `selected_node` — id выбранного узла (только для `tunnel`).
- `rules.json` — пользовательские маршруты.
- `server.json` — параметры VLESS-сервера (UUID, ключи Reality).
- `xray.log` — лог Xray.

## Поведение

- VPN-сервер на :443 запускается всегда, даже когда «туннель выключен».
- Кнопка power включает/выключает только **outbound**: при выключенном VPN все клиенты, подключённые к VLESS-серверу, всё равно получают доступ — просто их трафик идёт прямо (Direct).
- При выборе `Tunnel` + конкретного узла CGI генерирует новый `xray.json` (добавляет `vless`-outbound с узлом) и `systemctl restart wisd-xray`.

## Дев-режим / локальный запуск

Без VPS: можно открыть `site/index.html` прямо в браузере — он подцепит CGI по `http://localhost:8080`, если поднять `fcgiwrap` локально. См. `deploy/dev.md`.
