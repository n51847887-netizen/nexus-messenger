# ⚡ NEXUS Messenger

Полноценный мессенджер с реалтайм общением через WebSocket.

## Структура файлов

```
nexus/
├── app.py              # Flask backend (всё серверное)
├── templates/
│   └── index.html      # Фронтенд (весь UI)
├── requirements.txt    # Python зависимости
├── render.yaml         # Конфиг для Render.com
└── README.md
```

## Функции

- ✅ Регистрация / Вход по email
- ✅ Поиск пользователей
- ✅ Личные чаты (DM)
- ✅ Групповые чаты
- ✅ Реалтайм сообщения (WebSocket)
- ✅ Индикатор печати ("typing...")
- ✅ Онлайн-статус
- ✅ Редактирование сообщений
- ✅ Удаление сообщений
- ✅ Ответы на сообщения (reply)
- ✅ Реакции на сообщения (😂❤️🔥 и др.)
- ✅ Emoji-пикер
- ✅ Настройка профиля (аватар, цвет, эмодзи)
- ✅ Уведомления (toast)
- ✅ История сообщений
- ✅ Адаптив под мобильные

## Деплой на Render.com (бесплатно)

1. Загрузи всё на GitHub:
```bash
git init
git add .
git commit -m "NEXUS Messenger init"
git remote add origin https://github.com/ВАШ_ЮЗЕР/nexus-messenger.git
git push -u origin main
```

2. Иди на [render.com](https://render.com) → New → Web Service
3. Подключи GitHub репо
4. Render сам прочитает `render.yaml` и задеплоит
5. URL будет типа `https://nexus-messenger.onrender.com`

## Локальный запуск

```bash
pip install -r requirements.txt
python app.py
```

Открой `http://localhost:5000`

## Переменные окружения (опционально)

| Переменная | Описание |
|------------|----------|
| `SECRET_KEY` | Секретный ключ Flask (Render генерит сам) |
| `DATABASE_URL` | URL базы данных (по умолчанию SQLite) |
| `PORT` | Порт (по умолчанию 5000) |

## База данных

По умолчанию используется SQLite (файл `nexus.db`). 
Для продакшена рекомендуется подключить PostgreSQL через Render.
