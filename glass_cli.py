#!/usr/bin/env python3
import argparse
import getpass
import hashlib
import io
import json
import os
import socket
import sys
import tarfile
import time
from pathlib import Path

import requests

DEFAULT_SERVER = os.environ.get("GLASS_SERVER_URL", "http://127.0.0.1:8000")
CONFIG_FILE = ".glass.json"
IGNORE_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".DS_Store",
    CONFIG_FILE,
}


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def current_dir():
    return Path.cwd()


def config_path(base=None):
    base = base or current_dir()
    return base / CONFIG_FILE


def load_config(base=None):
    path = config_path(base)
    if not path.exists():
        die(f"{CONFIG_FILE} not found in {path.parent}. Pull a silicon first.")
    return json.loads(path.read_text())


def save_config(data, base=None):
    path = config_path(base)
    path.write_text(json.dumps(data, indent=2))


def folder_fingerprint(folder):
    raw = f"{socket.gethostname()}::{folder.resolve()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def iter_files(folder):
    for path in sorted(folder.rglob("*")):
        if path.is_dir():
            continue
        if any(part in IGNORE_NAMES for part in path.parts):
            continue
        yield path


def tree_hash(folder):
    digest = hashlib.sha256()
    for path in iter_files(folder):
        rel = path.relative_to(folder).as_posix().encode()
        digest.update(rel)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def build_archive(folder):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in iter_files(folder):
            tar.add(path, arcname=path.relative_to(folder).as_posix())
    buffer.seek(0)
    return buffer


def push_once(folder, *, quiet=False):
    cfg = load_config(folder)
    tree = tree_hash(folder)
    if tree == cfg.get("last_tree_hash"):
        if not quiet:
            print("No code changes. Skipping push.")
        return False

    archive = build_archive(folder)
    headers = {"X-Source-Token": cfg["source_token"]}
    url = f"{cfg['server_url'].rstrip('/')}/sync/api/silicons/{cfg['silicon_username']}/push/"

    for attempt in range(1, 4):
        response = requests.post(
            url,
            headers=headers,
            data={"tree_hash": tree},
            files={"archive": ("snapshot.tar.gz", archive.getvalue(), "application/gzip")},
            timeout=120,
        )
        if response.status_code == 401:
            if attempt == 3:
                die("Connector code is stale after 3 attempts. Generate a new connector from the dashboard and pull again.")
            time.sleep(2)
            continue
        response.raise_for_status()
        data = response.json()
        if data.get("created"):
            cfg["last_tree_hash"] = tree
            save_config(cfg, folder)
            if not quiet:
                print(f"Pushed snapshot {data['snapshot_id']} for {cfg['silicon_username']}.")
        else:
            cfg["last_tree_hash"] = tree
            save_config(cfg, folder)
            if not quiet:
                print("Remote already has this tree. Nothing new stored.")
        return data.get("created", False)
    return False


def command_pull(args):
    target = Path(args.folder_name)
    if target.exists():
        die(f"{target} already exists.")
    username = input("silicon username: ").strip().lower()
    connector_code = getpass.getpass("connector code: ").strip()
    target.mkdir(parents=True, exist_ok=False)

    payload = {
        "username": username,
        "connector_code": connector_code,
        "folder_label": target.name,
        "folder_fingerprint": folder_fingerprint(target),
    }
    server = args.server.rstrip("/")
    claim = requests.post(f"{server}/sync/api/pull/claim/", json=payload, timeout=30)
    if not claim.ok:
        target.rmdir()
        die(claim.json().get("error", "Pull claim failed."))
    data = claim.json()

    cfg = {
        "server_url": server,
        "silicon_username": username,
        "source_token": data["source_token"],
        "api_key": data["api_key"],
        "folder_fingerprint": folder_fingerprint(target),
        "last_tree_hash": data.get("latest_tree_hash", ""),
    }
    save_config(cfg, target)

    if data.get("has_snapshot"):
        download = requests.get(
            f"{server}/sync/api/silicons/{username}/latest.tar.gz",
            headers={"X-Source-Token": data["source_token"]},
            timeout=120,
        )
        download.raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(download.content), mode="r:gz") as tar:
            tar.extractall(target)
        print(f"Pulled {username} into {target}.")
    else:
        print(f"Claimed {username} into {target}. No snapshot exists yet.")


def command_push(args):
    folder = current_dir()
    if args.subcommand == "now":
        push_once(folder)
        return

    print("Hourly sync started. Press Ctrl+C to stop.")
    while True:
        push_once(folder, quiet=False)
        time.sleep(3600)


def build_parser():
    parser = argparse.ArgumentParser(prog="glass")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Glass server URL")

    subparsers = parser.add_subparsers(dest="command", required=True)

    push_parser = subparsers.add_parser("push")
    push_parser.set_defaults(func=command_push)
    push_parser.add_argument("subcommand", nargs="?", choices=["now"])

    pull_parser = subparsers.add_parser("pull")
    pull_parser.set_defaults(func=command_pull)
    pull_parser.add_argument("folder_name")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
