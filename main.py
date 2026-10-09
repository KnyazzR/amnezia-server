import os
import uuid
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, status, Depends
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI(title="Amnezia Config Proxy Server")

# 1. НАШ ключ безопасности
OUR_API_KEY = os.getenv("OUR_API_KEY")
if not OUR_API_KEY:
    raise RuntimeError("Переменная окружения OUR_API_KEY не задана!")

# 2. Настройки подключения к amneziawg-api (проект taphix)
AMNEZIA_API_URL = os.getenv("AMNEZIA_API_URL", "http://localhost:8000").rstrip("/")
AMNEZIA_API_TOKEN = os.getenv("AMNEZIA_API_TOKEN")
AMNEZIA_SERVER_ID = int(os.getenv("AMNEZIA_SERVER_ID", "1"))

if not AMNEZIA_API_TOKEN:
    raise RuntimeError("Переменная окружения AMNEZIA_API_TOKEN не задана!")

CONFIG_DIR = "configs"
os.makedirs(CONFIG_DIR, exist_ok=True)


async def verify_our_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Проверяет наш внутренний API-ключ (защита от спама)."""
    import hmac
    if not hmac.compare_digest(x_api_key, OUR_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


@app.get("/")
def root():
    return {"status": "running", "docs": "/docs"}


@app.get("/script", response_class=PlainTextResponse)
def get_script():
    """Отдаёт bash-скрипт для клиента (публично)."""
    return """#!/bin/bash
echo "=== Amnezia client setup ==="
# Здесь ваша логика применения скачанного конфига
echo "Done."
"""


@app.get("/generate", dependencies=[Depends(verify_our_api_key)])
def generate_config():
    """
    1. Делает запрос к amneziawg-api для создания клиента.
    2. Забирает готовый .conf файл.
    3. Сохраняет его у нас и отдаёт ссылку.
    """
    config_id = str(uuid.uuid4())[:8]
    client_name = f"client_{config_id}"
    
    # Дата истечения: +1 год от сегодня (формат DD.MM.YYYY, как требует amneziawg-api)
    expires_until = (datetime.now() + timedelta(days=365)).strftime("%d.%m.%Y")

    headers = {
        "Authorization": f"Bearer {AMNEZIA_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "server_id": AMNEZIA_SERVER_ID,
        "client_name": client_name,
        "expires_until": expires_until
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            # Шаг 1: Просим amneziawg-api создать клиента
            response = client.post(f"{AMNEZIA_API_URL}/api/clients", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # В документации taphix поле намеренно называется "succsess" (с опечаткой), проверяем оба варианта
            if not data.get("succsess") and not data.get("success"):
                raise HTTPException(status_code=500, detail=f"Amnezia API failed: {data}")
            
            conf_url = data["files"]["conf_url"]
            
            # Шаг 2: Скачиваем сам .conf файл
            # Если ссылка относительная, делаем её абсолютной
            if not conf_url.startswith("http"):
                conf_url = f"{AMNEZIA_API_URL}{conf_url}"
                
            conf_response = client.get(conf_url, headers=headers)
            conf_response.raise_for_status()
            conf_content = conf_response.text

    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка связи с Amnezia API: {str(e)}")

    # Шаг 3: Сохраняем конфиг локально у нас в Docker
    local_path = os.path.join(CONFIG_DIR, f"{config_id}.conf")
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(conf_content)

    return JSONResponse({
        "status": "success",
        "config_id": config_id,
        "client_name": client_name,
        "download_url": f"/configs/{config_id}",
    })


@app.get("/configs/{config_id}", dependencies=[Depends(verify_our_api_key)])
def get_config(config_id: str):
    """Отдаёт сохраненный конфиг по ID."""
    path = os.path.join(CONFIG_DIR, f"{config_id}.conf")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Config not found")
    
    with open(path, "r", encoding="utf-8") as f:
        return PlainTextResponse(f.read(), media_type="text/plain")