#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import power_sweep_remote_config as cfg
from power_sweep_remote_util import (
    connect,
    copy_remote_tree,
    expand_remote_path,
    expand_template,
    git_host_from_url,
    resolve_remote_path,
    run_local_command,
    run_remote_command,
    split_csv,
    split_node,
    trim,
    write_text,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeatable distributed power sweeps with client-side load and server-side power measurement.",
    )
    parser.add_argument("--hosts", help="Compatibility fallback for both client and server hosts.")
    parser.add_argument("--hosts-file", help="Compatibility fallback file for both client and server hosts.")
    parser.add_argument("--client-hosts", help="Comma-separated SSH hosts that run wrk2.")
    parser.add_argument("--client-hosts-file", help="File with one client host per line.")
    parser.add_argument("--server-hosts", help="Comma-separated SSH hosts that run the hotel stack.")
    parser.add_argument("--server-hosts-file", help="File with one server host per line.")
    parser.add_argument("--targets", default="all", help="Comma-separated targets or 'all'.")
    parser.add_argument("--governors", help="Comma-separated governors.")
    parser.add_argument("--ssh-user", default=cfg.SSH_USER, help="Optional SSH username.")
    parser.add_argument("--ssh-key", default=cfg.SSH_KEY_PATH, help="SSH private key for node access.")
    parser.add_argument("--private-key", default=cfg.PRIVATE_KEY_PATH, help="Deploy key copied to nodes for git clone/pull.")
    parser.add_argument("--clone-repo-url", default=cfg.CLONE_REPO_URL, help="Git URL used for remote clone.")
    parser.add_argument("--remote-repo-root", default=cfg.REMOTE_REPO_ROOT, help="Repository root on remote hosts.")
    parser.add_argument("--remote-key-path", default=cfg.REMOTE_KEY_PATH, help="Deploy key location on remote hosts.")
    parser.add_argument("--client-remote-script", default=cfg.REMOTE_CLIENT_SCRIPT, help="Client sweep script path relative to repo root.")
    parser.add_argument("--server-remote-script", default=cfg.REMOTE_SERVER_SCRIPT, help="Server power script path relative to repo root.")
    parser.add_argument("--server-stack-start-script", default=cfg.SERVER_STACK_START_SCRIPT, help="Remote stack start script path relative to repo root.")
    parser.add_argument("--server-stack-repo-root", help="Checkout root to use for the server stack. Defaults to --remote-repo-root.")
    parser.add_argument("--server-stack-config", help="Optional config file passed to start_process_stack.sh.")
    parser.add_argument("--server-stack-session", default=cfg.SERVER_STACK_SESSION, help="tmux session name for the server stack.")
    parser.add_argument("--prepare-server-stack", action="store_true", help="Build and start the bare-process server stack before the sweep.")
    parser.add_argument("--replace-server-stack", action="store_true", help="Replace any existing stack session/processes before starting.")
    parser.add_argument("--host-url-template", default=cfg.HOST_URL_TEMPLATE, help="Frontend URL template. %%h=host %%t=target %%i=index.")
    parser.add_argument("--remote-output-base", default=cfg.REMOTE_OUTPUT_BASE, help="Remote result root. Default: /tmp/hotelReservation-power-sweeps/<timestamp>.")
    parser.add_argument("--local-output-dir", help="Local result root. Default: hotelReservation/results/distributed_power_sweeps/<timestamp>.")
    parser.add_argument("--threads", type=int, default=cfg.THREADS)
    parser.add_argument("--connections", type=int, default=cfg.CONNECTIONS)
    parser.add_argument("--duration", type=int, default=cfg.DURATION_SECONDS)
    parser.add_argument("--rates", default=cfg.RATES_SPEC)
    parser.add_argument("--powerstat-interval", type=float, default=cfg.POWERSTAT_INTERVAL)
    parser.add_argument("--powerstat-source", default=cfg.POWERSTAT_SOURCE, choices=["auto", "rapl", "battery"])
    parser.add_argument("--settle-seconds", type=int, default=cfg.SETTLE_SECONDS)
    parser.add_argument("--frontend-wait-seconds", type=int, default=10)
    parser.add_argument("--skip-copy-back", action="store_true", help="Leave results only on remote hosts.")
    parser.add_argument("--refresh-repo", action="store_true", help="Run git fetch/pull on existing remote checkouts.")
    parser.add_argument("--bootstrap-only", action="store_true", help="Only copy the git key and clone/update remote checkouts.")
    return parser.parse_args()


def load_hosts_from_args(
    hosts: str | None,
    hosts_file: str | None,
    default_hosts: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    resolved_hosts: list[str] = []
    if hosts_file:
        file_path = Path(hosts_file)
        if not file_path.is_file():
            raise FileNotFoundError(f"hosts file not found: {file_path}")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            value = trim(line)
            if value and not value.startswith("#"):
                resolved_hosts.append(value)
    if hosts:
        resolved_hosts.extend(split_csv(hosts))
    if not resolved_hosts and default_hosts:
        resolved_hosts.extend(default_hosts)
    return resolved_hosts


def pick_targets(args: argparse.Namespace) -> list[str]:
    if not args.targets or args.targets == "all":
        return list(cfg.DEFAULT_TARGETS)
    return split_csv(args.targets)


def pick_governors(args: argparse.Namespace) -> list[str]:
    if not args.governors:
        return list(cfg.DEFAULT_GOVERNORS)
    return split_csv(args.governors)


def expand_rates(spec: str) -> list[int]:
    if ":" in spec:
        start, end, step = [int(part) for part in spec.split(":", 2)]
        return list(range(start, end + 1, step))
    return [int(part) for part in split_csv(spec)]


def sanitize_name(value: str) -> str:
    return value.replace("@", "_").replace("/", "_").replace(":", "_")


def ensure_remote_checkout(
    node: str,
    ssh_user: str,
    ssh_key: str | None,
    private_key: str | None,
    clone_repo_url: str,
    remote_repo_root: str,
    remote_key_path: str,
    refresh_repo: bool,
) -> str:
    default_user, host = split_node(node, ssh_user)
    conn = connect(host, default_user, ssh_key)
    try:
        git_host = git_host_from_url(clone_repo_url)
        remote_repo_root = expand_remote_path(remote_repo_root)
        remote_key_path = expand_remote_path(remote_key_path)
        if remote_repo_root.startswith("~/"):
            remote_repo_root = f"$HOME/{remote_repo_root[2:]}"
        if remote_key_path.startswith("~/"):
            remote_key_path = f"$HOME/{remote_key_path[2:]}"
        remote_parent = str(Path(remote_repo_root).parent)

        run_remote_command(conn, f"mkdir -p {shlex.quote(remote_parent)}", must_succeed=True)

        if private_key:
            sftp = conn.open_sftp()
            try:
                remote_tmp_key = f"/tmp/deathstarbench_deploy_key_{os.getpid()}"
                sftp.put(os.path.expanduser(private_key), remote_tmp_key)
            finally:
                sftp.close()

            bootstrap_cmd = f"""
set -euo pipefail
mkdir -p "$(dirname {shlex.quote(remote_key_path)})"
chmod 700 "$(dirname {shlex.quote(remote_key_path)})"
install -m 600 {shlex.quote(remote_tmp_key)} {shlex.quote(remote_key_path)}
rm -f {shlex.quote(remote_tmp_key)}
mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/known_hosts"
chmod 600 "$HOME/.ssh/known_hosts"
touch "$HOME/.ssh/config"
chmod 600 "$HOME/.ssh/config"
"""
            if git_host:
                bootstrap_cmd += f"""
ssh-keyscan -H {shlex.quote(git_host)} >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
python3 - <<'PY'
from pathlib import Path
host = {git_host!r}
identity = {remote_key_path!r}
config_path = Path.home() / ".ssh" / "config"
lines = config_path.read_text(encoding="utf-8").splitlines() if config_path.exists() else []
filtered = []
skip = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("Host ") and stripped.split(maxsplit=1)[1] == host:
        skip = True
        continue
    if skip and stripped.startswith("Host "):
        skip = False
    if not skip:
        filtered.append(line)
filtered.extend([
    f"Host {{host}}",
    f"  IdentityFile {{identity}}",
    "  IdentitiesOnly yes",
    "  StrictHostKeyChecking yes",
])
config_path.write_text("\\n".join(filtered) + "\\n", encoding="utf-8")
PY
"""
            run_remote_command(conn, f"bash -lc {shlex.quote(bootstrap_cmd)}", must_succeed=True)

        clone_cmd = f"""
set -euo pipefail
if [ ! -d {shlex.quote(remote_repo_root)}/.git ]; then
  git clone --recurse-submodules {shlex.quote(clone_repo_url)} {shlex.quote(remote_repo_root)}
  cd {shlex.quote(remote_repo_root)}
  git submodule update --init --recursive
elif [ "{'1' if refresh_repo else '0'}" = "1" ]; then
  cd {shlex.quote(remote_repo_root)}
  git fetch origin
  branch="$(git rev-parse --abbrev-ref HEAD)"
  git pull --ff-only origin "$branch"
  git submodule sync --recursive
  git submodule update --init --recursive
fi
"""
        run_remote_command(conn, f"bash -lc {shlex.quote(clone_cmd)}", must_succeed=True)
        return host
    finally:
        conn.close()


def copy_results(node: str, ssh_user: str, ssh_key: str | None, remote_dir: str, local_dir: Path) -> None:
    default_user, host = split_node(node, ssh_user)
    conn = connect(host, default_user, ssh_key)
    try:
        resolved = resolve_remote_path(conn, remote_dir)
        copy_remote_tree(conn, resolved, local_dir)
    finally:
        conn.close()


def run_remote_script(
    node: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_repo_root: str,
    script_path: str,
    argv: list[str],
) -> tuple[int, str, str]:
    default_user, host = split_node(node, ssh_user)
    conn = connect(host, default_user, ssh_key)
    try:
        repo_root = resolve_remote_path(conn, remote_repo_root)
        script = f"{repo_root}/{script_path}"
        command = ["bash", script, *argv]
        return run_remote_command(conn, shlex.join(command), must_succeed=False)
    finally:
        conn.close()


def prepare_server_stack(server: str, args: argparse.Namespace) -> tuple[int, str, str]:
    stack_repo_root = args.server_stack_repo_root or args.remote_repo_root
    argv = [
        "--repo-root",
        stack_repo_root,
        "--session",
        args.server_stack_session,
        "--frontend-url",
        "http://127.0.0.1:5000",
        "--wait-seconds",
        str(args.frontend_wait_seconds),
    ]
    if args.server_stack_config:
        argv.extend(["--config", args.server_stack_config])
    if args.replace_server_stack:
        argv.append("--replace-existing")
    return run_remote_script(
        server,
        args.ssh_user,
        args.ssh_key,
        args.remote_repo_root,
        args.server_stack_start_script,
        argv,
    )


def run_distributed_job(
    client: str,
    server: str,
    governor: str,
    target: str,
    frontend_url: str,
    remote_job_root: str,
    local_job_dir: Path,
    args: argparse.Namespace,
) -> tuple[int, str, str]:
    local_job_dir.mkdir(parents=True, exist_ok=True)
    rates = expand_rates(args.rates)
    client_root = f"{remote_job_root}/client"
    server_root = f"{remote_job_root}/server"

    combined_stdout: list[str] = []
    combined_stderr: list[str] = []

    for rate in rates:
        client_rate_dir = f"{client_root}/rate_{rate}"
        server_rate_dir = f"{server_root}/rate_{rate}"
        server_argv = [
            "--target",
            target,
            "--governor",
            governor,
            "--rate",
            str(rate),
            "--duration",
            str(args.duration),
            "--powerstat-interval",
            str(args.powerstat_interval),
            "--powerstat-source",
            args.powerstat_source,
            "--settle-seconds",
            str(args.settle_seconds),
            "--output-dir",
            server_rate_dir,
        ]
        client_argv = [
            "--target",
            target,
            "--host",
            frontend_url,
            "--threads",
            str(args.threads),
            "--connections",
            str(args.connections),
            "--duration",
            str(args.duration),
            "--rates",
            str(rate),
            "--settle-seconds",
            "0",
            "--output-dir",
            client_rate_dir,
        ]

        with ThreadPoolExecutor(max_workers=1) as executor:
            server_future = executor.submit(
                run_remote_script,
                server,
                args.ssh_user,
                args.ssh_key,
                args.remote_repo_root,
                args.server_remote_script,
                server_argv,
            )
            time.sleep(0.5)
            client_status, client_stdout, client_stderr = run_remote_script(
                client,
                args.ssh_user,
                args.ssh_key,
                args.remote_repo_root,
                args.client_remote_script,
                client_argv,
            )
            server_status, server_stdout, server_stderr = server_future.result()

        combined_stdout.extend([f"=== rate {rate} client ===\n{client_stdout}", f"=== rate {rate} server ===\n{server_stdout}"])
        combined_stderr.extend([f"=== rate {rate} client ===\n{client_stderr}", f"=== rate {rate} server ===\n{server_stderr}"])

        if client_status != 0 or server_status != 0:
            return 1, "\n".join(combined_stdout), "\n".join(combined_stderr)

    if not args.skip_copy_back:
        copy_results(client, args.ssh_user, args.ssh_key, client_root, local_job_dir / "client")
        copy_results(server, args.ssh_user, args.ssh_key, server_root, local_job_dir / "server")

        merged_csv = local_job_dir / "results.csv"
        run_local_command(
            [
                sys.executable,
                str(SCRIPT_DIR / "merge_distributed_power_results.py"),
                "--client",
                str(local_job_dir / "client"),
                "--server",
                str(local_job_dir / "server"),
                "--output",
                str(merged_csv),
            ],
            must_succeed=True,
        )

        for y_column, filename in [("avg_power_watts", "throughput_vs_power.png"), ("p99_ms", "throughput_vs_p99.png")]:
            run_local_command(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "plot_power_sweep.py"),
                    "--input",
                    str(merged_csv),
                    "--output",
                    str(local_job_dir / filename),
                    "--x-column",
                    "requests_sec",
                    "--y-column",
                    y_column,
                    "--title",
                    f"{target} {governor} {sanitize_name(client)} -> {sanitize_name(server)}",
                ],
                must_succeed=False,
            )

    return 0, "\n".join(combined_stdout), "\n".join(combined_stderr)


def main() -> int:
    args = parse_args()

    fallback_hosts = load_hosts_from_args(args.hosts, args.hosts_file, cfg.NODES)
    client_hosts = load_hosts_from_args(args.client_hosts or args.hosts, args.client_hosts_file or args.hosts_file, fallback_hosts)
    server_hosts = load_hosts_from_args(args.server_hosts or args.hosts, args.server_hosts_file or args.hosts_file, fallback_hosts)
    if not client_hosts:
        raise SystemExit("no client hosts specified")
    if not server_hosts:
        raise SystemExit("no server hosts specified")

    targets = pick_targets(args)
    governors = pick_governors(args)
    timestamp_value = timestamp()
    remote_output_base = args.remote_output_base or f"/tmp/hotelReservation-power-sweeps/{timestamp_value}"
    local_output_root = Path(args.local_output_dir or (Path(cfg.LOCAL_OUTPUT_DIR) / timestamp_value))
    local_output_root.mkdir(parents=True, exist_ok=True)

    unique_nodes = sorted(set(client_hosts + server_hosts))
    for node in unique_nodes:
        ensure_remote_checkout(
            node=node,
            ssh_user=args.ssh_user,
            ssh_key=args.ssh_key,
            private_key=args.private_key,
            clone_repo_url=args.clone_repo_url,
            remote_repo_root=args.remote_repo_root,
            remote_key_path=args.remote_key_path,
            refresh_repo=args.refresh_repo,
        )

    stack_repo_root = args.server_stack_repo_root or args.remote_repo_root
    for server in sorted(set(server_hosts)):
        ensure_remote_checkout(
            node=server,
            ssh_user=args.ssh_user,
            ssh_key=args.ssh_key,
            private_key=args.private_key,
            clone_repo_url=args.clone_repo_url,
            remote_repo_root=stack_repo_root,
            remote_key_path=args.remote_key_path,
            refresh_repo=args.refresh_repo,
        )
        if args.prepare_server_stack:
            status, stdout, stderr = prepare_server_stack(server, args)
            if status != 0:
                raise RuntimeError(stderr.strip() or stdout.strip() or f"failed to prepare server stack on {server}")

    if args.bootstrap_only:
        return 0

    jobs: list[tuple[str, str, str, str, str, Path, str]] = []
    pair_count = max(len(client_hosts), len(server_hosts))
    for index in range(pair_count):
        client = client_hosts[index % len(client_hosts)]
        server = server_hosts[index % len(server_hosts)]
        for governor in governors:
            for target in targets:
                frontend_url = expand_template(args.host_url_template, split_node(server, args.ssh_user)[1], target, index)
                remote_job_root = f"{remote_output_base}/{governor}/{index}_{sanitize_name(client)}_{sanitize_name(server)}_{target}"
                local_job_dir = local_output_root / governor / f"{index}_{sanitize_name(client)}_{sanitize_name(server)}_{target}"
                jobs.append((client, server, governor, target, frontend_url, local_job_dir, remote_job_root))

    overall_failures = 0
    for client, server, governor, target, frontend_url, local_job_dir, remote_job_root in jobs:
        status, stdout, stderr = run_distributed_job(
            client=client,
            server=server,
            governor=governor,
            target=target,
            frontend_url=frontend_url,
            remote_job_root=remote_job_root,
            local_job_dir=local_job_dir,
            args=args,
        )
        write_text(local_job_dir / "stdout.log", stdout)
        write_text(local_job_dir / "stderr.log", stderr)
        write_text(
            local_job_dir / "run.env",
            "\n".join(
                [
                    f"client={client}",
                    f"server={server}",
                    f"governor={governor}",
                    f"target={target}",
                    f"frontend_url={frontend_url}",
                    f"remote_output_root={remote_job_root}",
                    f"remote_repo_root={args.remote_repo_root}",
                    f"server_stack_repo_root={stack_repo_root}",
                    f"rates={args.rates}",
                    f"threads={args.threads}",
                    f"connections={args.connections}",
                    f"duration={args.duration}",
                    f"powerstat_interval={args.powerstat_interval}",
                ]
            )
            + "\n",
        )
        if status != 0:
            overall_failures += 1

    return 1 if overall_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
