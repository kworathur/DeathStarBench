#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import power_sweep_remote_config as cfg
from power_sweep_remote_util import (
    connect,
    expand_remote_path,
    expand_template,
    git_host_from_url,
    run_local_command,
    run_remote_command,
    split_csv,
    split_node,
    trim,
    write_text,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_hosts(args: argparse.Namespace) -> list[str]:
    hosts: list[str] = []
    if args.hosts_file:
        file_path = Path(args.hosts_file)
        if not file_path.is_file():
            raise FileNotFoundError(f"hosts file not found: {file_path}")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            value = trim(line)
            if value and not value.startswith("#"):
                hosts.append(value)
    if args.hosts:
        hosts.extend(split_csv(args.hosts))
    if not hosts:
        hosts.extend(cfg.NODES)
    return hosts


def pick_targets(args: argparse.Namespace) -> list[str]:
    if not args.targets or args.targets == "all":
        return list(cfg.DEFAULT_TARGETS)
    return split_csv(args.targets)


def pick_governors(args: argparse.Namespace) -> list[str]:
    if not args.governors:
        return list(cfg.DEFAULT_GOVERNORS)
    return split_csv(args.governors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone/update hotelReservation on remote nodes and run power sweeps in parallel.",
    )
    parser.add_argument("--hosts", help="Comma-separated SSH hostnames.")
    parser.add_argument("--hosts-file", help="File with one hostname per line.")
    parser.add_argument("--targets", default="all", help="Comma-separated targets or 'all'.")
    parser.add_argument("--governors", help="Comma-separated governors.")
    parser.add_argument("--ssh-user", default=cfg.SSH_USER, help="Optional SSH username.")
    parser.add_argument("--ssh-key", default=cfg.SSH_KEY_PATH, help="SSH private key for node access.")
    parser.add_argument("--private-key", default=cfg.PRIVATE_KEY_PATH, help="Deploy key copied to nodes for git clone/pull.")
    parser.add_argument("--clone-repo-url", default=cfg.CLONE_REPO_URL, help="Git URL used for remote clone.")
    parser.add_argument("--remote-repo-root", default=cfg.REMOTE_REPO_ROOT, help="Repository root on remote hosts.")
    parser.add_argument("--remote-script", default=cfg.REMOTE_SCRIPT, help="Sweep script path relative to repo root.")
    parser.add_argument("--remote-key-path", default=cfg.REMOTE_KEY_PATH, help="Deploy key location on remote hosts.")
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
    parser.add_argument("--skip-copy-back", action="store_true", help="Leave results only on remote hosts.")
    parser.add_argument("--refresh-repo", action="store_true", help="Run git fetch/pull on existing remote checkouts.")
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Only copy the git key and clone/update the remote checkout. Do not run any sweep jobs.",
    )
    return parser.parse_args()


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


def copy_results(
    node: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_dir: str,
    local_dir: Path,
) -> None:
    default_user, host = split_node(node, ssh_user)
    remote = f"{default_user}@{host}" if default_user else host
    local_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["scp", "-r", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        cmd.extend(["-i", os.path.expanduser(ssh_key)])
    cmd.extend([f"{remote}:{remote_dir}/.", str(local_dir)])
    run_local_command(cmd, must_succeed=False)


def run_job(
    node: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_repo_root: str,
    remote_script: str,
    governor: str,
    target: str,
    frontend_url: str,
    remote_output_dir: str,
    local_job_dir: Path,
    args: argparse.Namespace,
) -> tuple[str, str, int, str, str]:
    default_user, host = split_node(node, ssh_user)
    conn = connect(host, default_user, ssh_key)
    try:
        remote_cmd = [
            "bash",
            f"{expand_remote_path(remote_repo_root)}/{remote_script}",
            "--target",
            target,
            "--governor",
            governor,
            "--host",
            frontend_url,
            "--threads",
            str(args.threads),
            "--connections",
            str(args.connections),
            "--duration",
            str(args.duration),
            "--rates",
            args.rates,
            "--powerstat-interval",
            str(args.powerstat_interval),
            "--powerstat-source",
            args.powerstat_source,
            "--settle-seconds",
            str(args.settle_seconds),
            "--output-dir",
            remote_output_dir,
        ]
        command = shlex.join(remote_cmd)
        exit_code, stdout, stderr = run_remote_command(conn, command, must_succeed=False)
        write_text(local_job_dir / "stdout.log", stdout)
        write_text(local_job_dir / "stderr.log", stderr)
        return host, target, exit_code, stdout, stderr
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    hosts = load_hosts(args)
    targets = pick_targets(args)
    governors = pick_governors(args)

    if not hosts:
        raise SystemExit("No hosts provided. Use --hosts, --hosts-file, or configure NODES in scripts/power_sweep_remote_config.py.")
    if not args.bootstrap_only and len(hosts) < len(targets):
        raise SystemExit(f"Need at least as many hosts as targets. hosts={len(hosts)} targets={len(targets)}")
    if not args.clone_repo_url:
        raise SystemExit("Unable to determine clone URL. Pass --clone-repo-url explicitly or set it in power_sweep_remote_config.py.")

    run_id = timestamp()
    local_output_dir = Path(args.local_output_dir or Path(cfg.LOCAL_OUTPUT_DIR) / run_id)
    remote_output_base = args.remote_output_base or f"/tmp/hotelReservation-power-sweeps/{run_id}"
    local_output_dir.mkdir(parents=True, exist_ok=True)

    run_env = "\n".join(
        [
            f"hosts={' '.join(hosts)}",
            f"targets={' '.join(targets)}",
            f"governors={' '.join(governors)}",
            f"clone_repo_url={args.clone_repo_url}",
            f"remote_repo_root={args.remote_repo_root}",
            f"remote_script={args.remote_script}",
            f"remote_output_base={remote_output_base}",
            f"threads={args.threads}",
            f"connections={args.connections}",
            f"duration={args.duration}",
            f"rates={args.rates}",
            f"powerstat_interval={args.powerstat_interval}",
            f"powerstat_source={args.powerstat_source}",
            f"settle_seconds={args.settle_seconds}",
            f"refresh_repo={int(args.refresh_repo)}",
            f"copy_results={int(not args.skip_copy_back)}",
        ]
    )
    write_text(local_output_dir / "run.env", run_env + "\n")

    bootstrap_dir = local_output_dir / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(
                ensure_remote_checkout,
                node=hosts[index],
                ssh_user=args.ssh_user,
                ssh_key=args.ssh_key or None,
                private_key=args.private_key or None,
                clone_repo_url=args.clone_repo_url,
                remote_repo_root=args.remote_repo_root,
                remote_key_path=args.remote_key_path,
                refresh_repo=args.refresh_repo,
            ): hosts[index]
            for index in range(len(hosts) if args.bootstrap_only else len(targets))
        }
        for future in as_completed(futures):
            node = futures[future]
            log_path = bootstrap_dir / node.replace("@", "_")
            try:
                host = future.result()
                write_text(log_path / "status.log", f"bootstrapped={host}\n")
            except Exception as exc:
                write_text(log_path / "status.log", f"error={exc}\n")
                raise

    if args.bootstrap_only:
        print(f"Remote bootstrap finished successfully.\nLogs: {bootstrap_dir}")
        return 0

    overall_status = 0
    for governor in governors:
        phase_dir = local_output_dir / governor
        phase_dir.mkdir(parents=True, exist_ok=True)
        futures = {}
        with ThreadPoolExecutor(max_workers=len(targets)) as executor:
            for index, target in enumerate(targets):
                node = hosts[index]
                frontend_url = expand_template(args.host_url_template, split_node(node, args.ssh_user)[1], target, index)
                remote_output_dir = f"{remote_output_base}/{governor}/{target}"
                local_job_dir = phase_dir / f"{index}_{split_node(node, args.ssh_user)[1]}_{target}"
                local_job_dir.mkdir(parents=True, exist_ok=True)
                write_text(
                    local_job_dir / "job.env",
                    "\n".join(
                        [
                            f"host={split_node(node, args.ssh_user)[1]}",
                            f"target={target}",
                            f"governor={governor}",
                            f"frontend_url={frontend_url}",
                            f"remote_output_dir={remote_output_dir}",
                        ]
                    )
                    + "\n",
                )
                futures[
                    executor.submit(
                        run_job,
                        node=node,
                        ssh_user=args.ssh_user,
                        ssh_key=args.ssh_key or None,
                        remote_repo_root=args.remote_repo_root,
                        remote_script=args.remote_script,
                        governor=governor,
                        target=target,
                        frontend_url=frontend_url,
                        remote_output_dir=remote_output_dir,
                        local_job_dir=local_job_dir,
                        args=args,
                    )
                ] = (node, target, remote_output_dir, local_job_dir)

            failures = 0
            for future in as_completed(futures):
                node, target, remote_output_dir, local_job_dir = futures[future]
                host = split_node(node, args.ssh_user)[1]
                try:
                    _, _, exit_code, _, _ = future.result()
                    if exit_code != 0:
                        failures += 1
                    elif not args.skip_copy_back:
                        copy_results(node, args.ssh_user, args.ssh_key or None, remote_output_dir, local_job_dir / "results")
                    write_text(local_job_dir / "status.log", f"status={'ok' if exit_code == 0 else 'failed'}\n")
                except Exception as exc:
                    failures += 1
                    write_text(local_job_dir / "status.log", f"status=failed\nerror={exc}\n")
                    print(f"Governor={governor} host={host} target={target} failed: {exc}", file=sys.stderr)

            if failures:
                overall_status = 1
                print(f"Governor phase '{governor}' finished with {failures} failure(s).", file=sys.stderr)
                break

    if overall_status:
        print(f"Distributed power sweep finished with failures. Check logs under {local_output_dir}.", file=sys.stderr)
        return overall_status

    print(f"Distributed power sweep finished successfully.\nResults: {local_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
