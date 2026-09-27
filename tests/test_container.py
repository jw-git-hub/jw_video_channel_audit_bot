"""Контейнер (ТЗ, раздел 10, 14.3): образ, compose и .dockerignore проверяются статически — Docker на Маке нет,
сборка образа — на сервере."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
BOT = COMPOSE["services"]["bot"]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = [line for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#")]


def test_project_name_is_fixed():
    assert COMPOSE["name"] == "jw_video_channel_audit_bot"


def test_container_is_isolated_and_limited():
    assert "network_mode" not in BOT
    assert BOT["read_only"] is True
    assert BOT["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in BOT["security_opt"]
    assert BOT["mem_limit"] == BOT["memswap_limit"] == "256m"
    assert BOT["cpus"] == 0.5
    assert BOT["pids_limit"] == 64
    assert BOT["dns"] == ["1.1.1.1", "8.8.8.8"]


def test_own_network_next_to_the_checker():
    """Своя подсеть и мост: у чекера — 172.30.99.0/24 и br-sitecheck (ТЗ, С3)."""
    network = COMPOSE["networks"]["channel_audit"]
    assert BOT["networks"] == ["channel_audit"]
    assert network["enable_ipv6"] is False
    assert network["driver_opts"]["com.docker.network.bridge.name"] == "br-chaudit"
    assert network["ipam"]["config"][0]["subnet"] == "172.30.98.0/24"


def test_data_folder_and_healthcheck():
    assert BOT["volumes"] == ["./data:/app/data"]
    assert BOT["environment"]["DATA_DIR"] == "/app/data"
    assert "/tmp/alive" in " ".join(BOT["healthcheck"]["test"])


def test_secrets_come_only_at_runtime():
    assert BOT["env_file"] == ".env"
    assert DOCKERIGNORE[0] == "*"
    assert not [rule for rule in DOCKERIGNORE if rule.startswith("!") and ".env" in rule]


def test_image_gets_only_the_bot_with_banners_and_requirements():
    """Полосы лежат в bot/assets и едут в образ; _avatars/, шрифты генератора и документы — нет (ТЗ, 14.3)."""
    assert [rule for rule in DOCKERIGNORE if rule.startswith("!")] == ["!requirements.txt", "!bot/"]


def test_image_runs_as_unprivileged_user():
    assert "USER 10001:10001" in DOCKERFILE


def test_base_python_version_is_pinned_exactly():
    assert re.search(r"^FROM python:3\.12\.\d+-slim$", DOCKERFILE, re.MULTILINE)


def test_certificates_are_not_stripped_from_base_image():
    # Хранилище сертификатов — системное, из пакета ca-certificates: им пользуются запросы к Google и Telegram.
    # Смотрим только инструкции, не комментарии, — иначе их же слова роняли бы тест.
    instructions = "\n".join(line for line in DOCKERFILE.splitlines() if not line.strip().startswith("#"))
    assert "alpine" not in instructions
    assert "apt-get remove" not in instructions
    assert "apt-get purge" not in instructions
