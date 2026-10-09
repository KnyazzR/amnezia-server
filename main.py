import os
import json
import uuid
import paramiko
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI(title="Amnezia Config Server")

# Настройки подключения к серверу с Amnezia
AMNEZIA_HOST = os.getenv("AMNEZIA_HOST", "192.168.1.100")  # IP сервера с Amnezia
AMNEZIA_PORT = int(os.getenv("AMNEZIA_PORT", "22"))
AMNEZIA_USER = os.getenv("AMNEZIA_USER", "root")
AMNEZIA_KEY_PATH = os.getenv("AMNEZIA_KEY_PATH", "/app/ssh_key")  # приватный SSH-ключ

# Имя контейнера с AmneziaWG (уточните через `docker ps`)
AMNEZIA_CONTAINER = os.getenv("AMNEZIA_CONTAINER", "amnezia-awg")

# Путь к конфигу внутри контейнера
WG_CONFIG_PATH = os.getenv("WG_CONFIG_PATH", "/etc/wireguard/wg0.conf")

CONFIG_DIR = "configs"
os.makedirs(CONFIG_DIR, exist_ok=True)


def get_ssh_client():
    """SSH-подключение к серверу с Amnezia."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=AMNEZIA_HOST,
            port=AMNEZIA_PORT,
            username=AMNEZIA_USER,
            key_filename=AMNEZIA_KEY_PATH,
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"SSH connection failed: {e}")
    return client


def run_remote(client, command: str) -> str:
    """Выполняет команду на удалённом сервере."""
    stdin, stdout, stderr = client.exec_command(command, timeout=30)
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode()
    if exit_code != 0:
        raise HTTPException(status_code=500, detail=f"Remote command failed: {err}")
    return stdout.read().decode()


@app.get("/script", response_class=PlainTextResponse)
def get_script():
    """Отдаёт bash-скрипт для клиента."""
    return """#!/bin/bash
set -e
echo "=== Amnezia client setup ==="
# Здесь ваша логика применения конфига
echo "Done."
"""


@app.get("/generate")
def generate_config():
    """Реально создаёт нового клиента AmneziaWG на сервере."""
    config_id = str(uuid.uuid4())[:8]
    client_name = f"client_{config_id}"

    ssh = get_ssh_client()
    try:
        # ШАГ 1. Генерируем ключи для нового клиента
        gen_private_cmd = f"docker exec {AMNEZIA_CONTAINER} wg genkey"
        client_private_key = run_remote(ssh, gen_private_cmd).strip()

        gen_public_cmd = f"docker exec {AMNEZIA_CONTAINER} sh -c 'echo {client_private_key} | wg pubkey'"
        client_public_key = run_remote(ssh, gen_public_cmd).strip()

        # ШАГ 2. Получаем текущий конфиг сервера
        get_server_conf_cmd = f"docker exec {AMNEZIA_CONTAINER} cat {WG_CONFIG_PATH}"
        server_conf = run_remote(ssh, get_server_conf_cmd)

        # Парсим параметры сервера
        server_public_key = ""
        server_port = "51820"
        allowed_ips = "0.0.0.0/0, ::/0"
        dns = "1.1.1.1"
        
        for line in server_conf.split("\n"):
            if line.startswith("PublicKey"):
                server_public_key = line.split("=")[1].strip()
            elif line.startswith("ListenPort"):
                server_port = line.split("=")[1].strip()
            elif line.startswith("DNS"):
                dns = line.split("=")[1].strip()

        # ШАГ 3. Добавляем нового peer в конфиг сервера
        # Находим следующий свободный IP (упрощённо - можно улучшить)
        peer_ip = f"10.8.1.{100 + hash(config_id) % 100}"
        
        add_peer_cmd = f"""docker exec {AMNEZIA_CONTAINER} sh -c 'cat >> {WG_CONFIG_PATH} << EOF

[Peer]
# {client_name}
PublicKey = {client_public_key}
AllowedIPs = {peer_ip}/32
EOF'"""
        run_remote(ssh, add_peer_cmd)

        # ШАГ 4. Перезагружаем WireGuard для применения изменений
        reload_cmd = f"docker exec {AMNEZIA_CONTAINER} wg syncconf {WG_CONFIG_PATH} <(wg-quick strip {WG_CONFIG_PATH})"
        try:
            run_remote(ssh, reload_cmd)
        except:
            # Если wg syncconf не работает, просто перезапускаем контейнер
            restart_cmd = f"docker restart {AMNEZIA_CONTAINER}"
            run_remote(ssh, restart_cmd)

        # ШАГ 5. Получаем Amnezia-специфичные параметры (Jc, Jmin, Jmax и т.д.)
        # Эти параметры обычно в переменных окружения контейнера или в конфиге
        get_amnezia_params_cmd = f"docker exec {AMNEZIA_CONTAINER} cat /etc/wireguard/wg0.conf | grep -E '^(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4)'"
        amnezia_params_raw = run_remote(ssh, get_amnezia_params_cmd)
        
        # Парсим Amnezia-параметры
        amnezia_params = {}
        for line in amnezia_params_raw.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                amnezia_params[key.strip()] = value.strip()

        # ШАГ 6. Формируем клиентский конфиг
        client_config = f"""[Interface]
PrivateKey = {client_private_key}
Address = {peer_ip}/24
DNS = {dns}
Jc = {amnezia_params.get('Jc', '4')}
Jmin = {amnezia_params.get('Jmin', '40')}
Jmax = {amnezia_params.get('Jmax', '70')}
S1 = {amnezia_params.get('S1', '78')}
S2 = {amnezia_params.get('S2', '24')}
H1 = {amnezia_params.get('H1', '123456789')}
H2 = {amnezia_params.get('H2', '987654321')}
H3 = {amnezia_params.get('H3', '112233445')}
H4 = {amnezia_params.get('H4', '556677889')}

[Peer]
PublicKey = {server_public_key}
Endpoint = {AMNEZIA_HOST}:{server_port}
AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
"""

        # Сохраняем конфиг локально
        local_path = os.path.join(CONFIG_DIR, f"{config_id}.conf")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(client_config)

    finally:
        ssh.close()

    return JSONResponse({
        "status": "success",
        "config_id": config_id,
        "client_name": client_name,
        "client_ip": peer_ip,
        "download_url": f"/configs/{config_id}",
    })


@app.get("/configs/{config_id}")
def get_config(config_id: str):
    """Отдаёт готовый конфиг."""
    path = os.path.join(CONFIG_DIR, f"{config_id}.conf")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Config not found")
    
    with open(path, "r", encoding="utf-8") as f:
        return PlainTextResponse(f.read(), media_type="text/plain")