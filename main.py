import os
import json
import uuid
import subprocess
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Amnezia Config Server")

# Папка для хранения сгенерированных конфигов
CONFIG_DIR = "configs"
os.makedirs(CONFIG_DIR, exist_ok=True)

@app.get("/")
def root():
    return {"status": "Server is running", "endpoints": ["/script", "/generate", "/configs/{id}"]}

# 1. Эндпоинт, который отдает скрипт с конфигами
@app.get("/script", response_class=PlainTextResponse)
def get_script():
    # Здесь может быть ваш готовый bash/python скрипт
    script_content = """#!/bin/bash
echo "=== Amnezia Setup Script ==="
echo "Применяем конфигурацию..."
# Ваш код настройки амнезии
# amnezia-cli apply --config /path/to/config
echo "Готово!"
"""
    return script_content

# 2. Эндпоинт, который "просит" амнезию создать конфиги
@app.get("/generate")
def generate_config():
    config_id = str(uuid.uuid4())[:8]
    config_path = os.path.join(CONFIG_DIR, f"{config_id}.json")
    
    # ВАРИАНТ А: Если у вас есть CLI утилита Амнезии, вызываем её
    # try:
    #     subprocess.run(["amnezia-cli", "generate", "--output", config_path], check=True)
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Amnezia CLI error: {str(e)}")

    # ВАРИАНТ Б: Генерируем конфиг программно (пример для AmneziaWG/WireGuard)
    # В реальности здесь должен быть генератор ключей (wg genkey)
    mock_config = {
        "hostName": "127.0.0.1",
        "port": 51820,
        "client_ip": "10.8.1.2",
        "protocol": "awg",
        "config_id": config_id,
        "Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 78, "S2": 24, "H1": 123456789, "H2": 987654321, "H3": 112233445, "H4": 556677889
    }
    
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(mock_config, f, indent=4)

    return {
        "status": "success",
        "message": "Amnezia asked to create config, done!",
        "config_id": config_id,
        "download_url": f"/configs/{config_id}"
    }

# 3. Эндпоинт для скачивания уже созданного конфига
@app.get("/configs/{config_id}")
def get_config(config_id: str):
    config_path = os.path.join(CONFIG_DIR, f"{config_id}.json")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Config not found")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)