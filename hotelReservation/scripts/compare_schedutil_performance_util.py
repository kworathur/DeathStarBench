#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path


def split_node(node: str, default_user: str) -> tuple[str, str]:
    if "@" in node:
        user, host = node.split("@", 1)
        return (user or default_user), host
    return default_user, node


def trim(value: str) -> str:
    return value.strip()


def split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def expand_template(template: str, host: str, target: str, index: int) -> str:
    value = template.replace("%h", host)
    value = value.replace("%t", target)
    value = value.replace("%i", str(index))
    return value


def expand_remote_path(path: str) -> str:
    if path.startswith("/") or path.startswith("~"):
        return path
    return f"~/{path}"


def git_host_from_url(url: str) -> str | None:
    if not url:
        return None
    if url.startswith("ssh://"):
        return url.split("ssh://", 1)[1].split("@")[-1].split("/", 1)[0].split(":", 1)[0]
    if "@" in url and ":" in url:
        return url.split("@", 1)[1].split(":", 1)[0]
    if url.startswith("http://") or url.startswith("https://"):
        return url.split("://", 1)[1].split("/", 1)[0]
    return None


def _load_paramiko():
    try:
        import paramiko  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing Python dependency 'paramiko'. Install it with `sudo apt install -y python3-paramiko` "
            "or run `./scripts/install.sh`."
        ) from exc
    return paramiko


def load_private_key(key_path: str):
    paramiko = _load_paramiko()
    expanded = os.path.expanduser(key_path)
    try:
        return paramiko.Ed25519Key.from_private_key_file(expanded)
    except Exception:
        return paramiko.RSAKey.from_private_key_file(expanded)


def connect(host: str, user: str, key_path: str | None):
    paramiko = _load_paramiko()
    conn = paramiko.SSHClient()
    conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"hostname": host}
    if user:
        kwargs["username"] = user
    if key_path:
        kwargs["pkey"] = load_private_key(key_path)
    conn.connect(**kwargs)
    return conn


def run_remote_command(
    conn,
    cmd: str,
    must_succeed: bool = True,
) -> tuple[int, str, str]:
    session = conn.get_transport().open_session()
    session.exec_command(cmd)

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    buf_size = 4096

    while True:
        drained = False
        while session.recv_ready():
            stdout_chunks.append(session.recv(buf_size))
            drained = True
        while session.recv_stderr_ready():
            stderr_chunks.append(session.recv_stderr(buf_size))
            drained = True
        if session.exit_status_ready():
            exit_status = session.recv_exit_status()
            while session.recv_ready():
                stdout_chunks.append(session.recv(buf_size))
            while session.recv_stderr_ready():
                stderr_chunks.append(session.recv_stderr(buf_size))
            break
        if not drained:
            time.sleep(0.1)

    stdout = b"".join(stdout_chunks).decode("utf-8", "ignore")
    stderr = b"".join(stderr_chunks).decode("utf-8", "ignore")
    if must_succeed and exit_status != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or f"remote command failed: {cmd}")
    return exit_status, stdout, stderr


def run_local_command(cmd: list[str], must_succeed: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if must_succeed and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"local command failed: {shlex.join(cmd)}")
    return result


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
