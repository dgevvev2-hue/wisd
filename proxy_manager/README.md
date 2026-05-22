# Proxy Manager Android App

Приложение для Android для управления прокси с возможностью выбора приложений (YouTube и др.)

## Функции
- Выбор приложений для маршрутизации через прокси (YouTube, TikTok, Instagram, Telegram)
- Добавление/удаление прокси серверов
- Автоматическое подключение к прокси роутера (192.168.0.1:1081)
- Status мониторинг

## Установка Flutter SDK
1. Скачайте Flutter SDK с https://flutter.dev/docs/get-started/install/windows
2. Распакуйте в C:\flutter
3. Добавьте в PATH: C:\flutter\bin

## Сборка APK
```bash
cd proxy_manager
flutter pub get
flutter build apk --release
```

APK будет в: build/app/outputs/flutter-apk/app-release.apk
