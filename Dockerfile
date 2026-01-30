# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости (если нужны)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы приложения
COPY . .

# Открываем порт
EXPOSE 5000

# Переменные окружения (можно переопределить через docker-compose или .env)
ENV PORT=5000
ENV PYTHONUNBUFFERED=1

# Запускаем приложение
CMD ["python", "main.py"]
