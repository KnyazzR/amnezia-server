# Используем легкий образ Python
FROM python:3.11-slim

# Если вам нужны системные утилиты (например, wireguard-tools для генерации ключей), раскомментируйте:
# RUN apt-get update && apt-get install -y wireguard-tools && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY main.py .

# Создаем папку для конфигов
RUN mkdir -p configs

# Открываем порт
EXPOSE 80

# Запускаем сервер
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]