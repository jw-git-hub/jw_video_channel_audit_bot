import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COPIED = ("deploy/deploy.sh", "scripts/check_secrets.py", "bot/core/secret_patterns.py")
LOCAL_CONFIG = 'DEPLOY_HOST=test-host\nDEPLOY_USER=tester\nDEPLOY_PATH="/srv/bot folder"\n'
FAKE_SSH = """#!/usr/bin/env bash
command="${@: -1}"
printf '%s\\n' "$command" >> "$SSH_LOG"
case "$command" in
  *"git rev-parse HEAD"*) printf '%s\\n' "$FAKE_REMOTE_HEAD" ;;
esac
exit 0
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    for relative in COPIED:
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, work / relative)
    (work / ".gitignore").write_text("/deploy/*.local.env\n", encoding="utf-8")
    (work / "deploy" / "deploy.local.env").write_text(LOCAL_CONFIG, encoding="utf-8")
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", "t@example.invalid")
    git(work, "config", "user.name", "t")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "one")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    return work


def fake_ssh(project: Path, script: str) -> dict[str, str]:
    fake_bin = project.parent / "bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "ssh").write_text(script, encoding="utf-8")
    (fake_bin / "ssh").chmod(0o755)
    return {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}


def run_deploy(project: Path, environ: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "deploy/deploy.sh", *args], cwd=project, env=environ, capture_output=True,
                          text=True, timeout=60)


def deploy(project: Path, *args: str, remote_head: str | None = None) -> tuple[subprocess.CompletedProcess, list[str]]:
    log = project.parent / "ssh.log"
    environ = {**fake_ssh(project, FAKE_SSH), "SSH_LOG": str(log),
               "FAKE_REMOTE_HEAD": remote_head or git(project, "rev-parse", "HEAD")}
    result = run_deploy(project, environ, *args)
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def deploy_with_ssh_script(project: Path, ssh_script: str, **extra_env: str) -> subprocess.CompletedProcess:
    """Подмена ssh произвольным скриптом — для сценариев, где ответ зависит от самой команды."""
    return run_deploy(project, {**fake_ssh(project, ssh_script), **extra_env})


def script_text() -> str:
    return (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")


def test_happy_path_checks_out_exact_commit_then_restarts(project):
    result, commands = deploy(project)
    assert result.returncode == 0, result.stderr
    sha = git(project, "rev-parse", "HEAD")
    steps = ["/.env", "stat -c %u", "git status --porcelain", f"git checkout --quiet --detach {sha}",
             "docker compose build", "docker compose logs"]
    positions = [next(index for index, command in enumerate(commands) if step in command) for step in steps]
    assert positions == sorted(positions)
    assert "/srv/bot\\ folder" in commands[0]


def test_this_bot_has_no_network_guard_step():
    """Защиты сети чекера здесь нет (ТЗ, раздел 10) — и выкладка её не проверяет."""
    assert "systemctl" not in script_text() and "firewall" not in script_text()


def test_dirty_tree_stops_before_touching_server(project):
    (project / "new.txt").write_text("x", encoding="utf-8")
    result, commands = deploy(project)
    assert result.returncode == 1
    assert "есть незакоммиченные изменения" in result.stderr
    assert commands == []
    assert "откат" not in result.stderr.lower()  # сервер ещё не тронут — подсказка не к месту


def test_unpushed_commit_stops(project):
    """Без аргумента выкладывается только HEAD, точно равный origin/main: отставший прошёл бы молча."""
    commit(project, "two.txt")
    result, commands = deploy(project)
    assert result.returncode == 1
    assert "не совпадает с origin/main" in result.stderr
    assert commands == []


def test_explicit_missing_commit_stops(project):
    commit(project, "two.txt")
    result, commands = deploy(project, git(project, "rev-parse", "HEAD"))
    assert result.returncode == 1
    assert "нет в origin/main" in result.stderr
    assert commands == []


def test_invalid_sha_argument_fails_in_russian(project):
    result, commands = deploy(project, "not-a-real-commit")
    assert result.returncode == 1
    assert "не найден коммит" in result.stderr
    assert commands == []


def test_missing_local_config_stops(project):
    (project / "deploy" / "deploy.local.env").unlink()
    result, _ = deploy(project)
    assert result.returncode == 1
    assert "нет deploy/deploy.local.env" in result.stderr


def test_rollback_to_older_pushed_commit(project):
    first = git(project, "rev-parse", "HEAD")
    commit(project, "two.txt")
    git(project, "push", "-q", "origin", "main")
    result, commands = deploy(project, first, remote_head=first)
    assert result.returncode == 0, result.stderr
    assert any(f"git checkout --quiet --detach {first}" in command for command in commands)


def test_deploy_never_copies_env():
    assert "scp" not in script_text() and "< .env" not in script_text() and "cat .env" not in script_text()


def test_health_wait_is_sixty_seconds_by_a_real_deadline():
    """ТЗ, 14.2 п. 5: ждать healthy до 60 секунд — по часам (SECONDS), а не числом проходов цикла."""
    assert "HEALTH_WAIT_SECONDS=60" in script_text()
    assert "SECONDS" in script_text() and "seq $HEALTH_WAIT_SECONDS" not in script_text()


def test_unreachable_host_says_there_is_no_connection(project):
    """Выкладка ходит только по домашней сети: код ssh 255 — нет связи с сервером, про Tailscale ни слова."""
    result = deploy_with_ssh_script(project, "#!/usr/bin/env bash\nexit 255\n")
    assert result.returncode == 1
    assert "нет связи с сервером" in result.stderr
    assert "Tailscale" not in result.stderr


def test_remote_check_failure_keeps_specific_message(project):
    result = deploy_with_ssh_script(project, "#!/usr/bin/env bash\nexit 1\n")
    assert result.returncode == 1
    assert "нет .env на сервере" in result.stderr
    assert "нет связи с сервером" not in result.stderr


def test_deploy_has_a_single_helper_for_remote_failures():
    assert script_text().count("SSH_UNREACHABLE_EXIT_CODE") == 2  # константа и одна проверка в помощнике


def test_connection_lost_mid_deploy_says_there_is_no_connection(project):
    ssh_script = """#!/usr/bin/env bash
command="${@: -1}"
case "$command" in
  *"docker compose build"*) exit 255 ;;
  *"git rev-parse HEAD"*) printf '%s\\n' "$FAKE_REMOTE_HEAD" ;;
  *) exit 0 ;;
esac
"""
    result = deploy_with_ssh_script(project, ssh_script, FAKE_REMOTE_HEAD=git(project, "rev-parse", "HEAD"))
    assert result.returncode == 1
    assert "нет связи с сервером" in result.stderr


def test_failure_after_server_touched_suggests_rollback_to_previous_sha(project):
    previous_sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    ssh_script = """#!/usr/bin/env bash
command="${@: -1}"
case "$command" in
  *"git checkout"*) exit 1 ;;
  *"docker compose ps -a -q bot"*) echo "existing-container-id" ;;
  *"git rev-parse HEAD"*) printf '%s\\n' "$PREVIOUS_SHA" ;;
  *) exit 0 ;;
esac
"""
    result = deploy_with_ssh_script(project, ssh_script, PREVIOUS_SHA=previous_sha)
    assert result.returncode == 1
    assert f"deploy/deploy.sh {previous_sha}" in result.stderr


def test_failure_after_server_touched_on_first_deploy_says_nothing_to_roll_back_to(project):
    """Свежий клон отвечает на `git rev-parse HEAD` непустым sha (это его собственный HEAD, не пустая строка) —
    без строки deploy.sh, которая обнуляет PREVIOUS_SHA_ON_SERVER при отсутствии контейнера, подсказка отката
    ссылалась бы именно на этот sha, а не говорила «откатывать некуда»."""
    fresh_clone_sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    ssh_script = """#!/usr/bin/env bash
command="${@: -1}"
case "$command" in
  *"git checkout"*) exit 1 ;;
  *"docker compose ps -a -q bot"*) : ;;
  *"git rev-parse HEAD"*) printf '%s\\n' "$FRESH_CLONE_SHA" ;;
  *) exit 0 ;;
esac
"""
    result = deploy_with_ssh_script(project, ssh_script, FRESH_CLONE_SHA=fresh_clone_sha)
    assert result.returncode == 1
    assert "откатывать некуда" in result.stderr.lower()
    assert fresh_clone_sha not in result.stderr
