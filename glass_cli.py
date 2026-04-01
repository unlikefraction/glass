#!/usr/bin/env python3
import argparse
import getpass
import hashlib
import json
import io
import mimetypes
import os
import socket
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_SERVER = os.environ.get("GLASS_SERVER_URL", "https://glass.unlikefraction.com")
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


def read_json_response(response):
    payload = response.read().decode()
    if not payload:
        return {}
    return json.loads(payload)


def api_request(url, *, method="GET", headers=None, json_body=None, form=None, files=None, timeout=120):
    headers = dict(headers or {})
    data = None

    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None or files is not None:
        boundary = f"glass-{hashlib.sha256(os.urandom(16)).hexdigest()}"
        body = io.BytesIO()

        for key, value in (form or {}).items():
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.write(str(value).encode())
            body.write(b"\r\n")

        for key, file_info in (files or {}).items():
            filename, content, content_type = file_info
            body.write(f"--{boundary}\r\n".encode())
            body.write(
                f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode()
            )
            body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.write(content)
            body.write(b"\r\n")

        body.write(f"--{boundary}--\r\n".encode())
        data = body.getvalue()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def current_dir():
    return Path.cwd()


def config_path(base=None):
    base = base or current_dir()
    return base / CONFIG_FILE


def load_config(base=None):
    path = config_path(base)
    if not path.exists():
        die(f"{CONFIG_FILE} not found in {path.parent}. Pull or bind this folder first.")
    return json.loads(path.read_text())


def save_config(data, base=None):
    path = config_path(base)
    path.write_text(json.dumps(data, indent=2))


def ensure_env_value(env_path, key, value):
    lines = []
    seen = False
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    out = []
    for line in lines:
        if line.startswith(f"{key} ="):
            out.append(f'{key} = "{value}"')
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f'{key} = "{value}"')
    env_path.write_text("\n".join(out).rstrip() + "\n")


def bootstrap_silicon_folder(target, cfg):
    silicon_json = target / "silicon.json"
    env_py = target / "env.py"

    silicon_data = {
        "name": "Silicon",
        "address": cfg["silicon_username"],
        "version": "1.0",
        "run": "python main.py",
        "workers": {
            "terminal": ["chatgpt", "claude"],
        },
        "glass": {
            "server_url": cfg["server_url"],
            "silicon_username": cfg["silicon_username"],
            "api_key": cfg["api_key"],
            "source_token": cfg["source_token"],
        },
    }
    if silicon_json.exists():
        try:
            current = json.loads(silicon_json.read_text())
        except json.JSONDecodeError:
            current = {}
        current.update(
            {
                "address": cfg["silicon_username"],
                "glass": silicon_data["glass"],
            }
        )
        if "name" not in current:
            current["name"] = "Silicon"
        if "version" not in current:
            current["version"] = "1.0"
        if "run" not in current:
            current["run"] = "python main.py"
        if "workers" not in current:
            current["workers"] = {"terminal": ["chatgpt", "claude"]}
        silicon_data = current
    silicon_json.write_text(json.dumps(silicon_data, indent=4) + "\n")

    ensure_env_value(env_py, "GLASS_API_KEY", cfg["api_key"])


def claim_binding(server, username, connector_code, folder):
    payload = {
        "username": username,
        "connector_code": connector_code,
        "folder_label": folder.name,
        "folder_fingerprint": folder_fingerprint(folder),
    }
    status, _, response_body = api_request(
        f"{server.rstrip('/')}/sync/api/pull/claim/",
        method="POST",
        json_body=payload,
        timeout=30,
    )
    if status < 200 or status >= 300:
        try:
            data = json.loads(response_body.decode())
            return None, data.get("error", "Claim failed.")
        except Exception:
            return None, "Claim failed."

    data = json.loads(response_body.decode() or "{}")
    cfg = {
        "server_url": server.rstrip("/"),
        "silicon_username": username,
        "source_token": data["source_token"],
        "api_key": data["api_key"],
        "folder_fingerprint": folder_fingerprint(folder),
        "last_tree_hash": data.get("latest_tree_hash", ""),
    }
    save_config(cfg, folder)
    bootstrap_silicon_folder(folder, cfg)
    return cfg, None


def bind_existing_folder(folder, server):
    print("This folder is not connected to Glass yet.")
    print("Create the silicon profile in the Glass dashboard first if it does not exist.")
    username = input("silicon profile username: ").strip().lower()
    if not username:
        die("A silicon profile username is required.")
    connector_code = getpass.getpass("connector code: ").strip()
    if not connector_code:
        die("A connector code is required.")

    cfg, err = claim_binding(server, username, connector_code, folder)
    if err:
        die(err)

    print(f"Bound this folder to {cfg['silicon_username']}.")
    return cfg


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


def push_once(folder, server, *, quiet=False):
    cfg_path = config_path(folder)
    if not cfg_path.exists():
        cfg = bind_existing_folder(folder, server)
    else:
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
        status, _, payload = api_request(
            url,
            headers=headers,
            method="POST",
            form={"tree_hash": tree},
            files={"archive": ("snapshot.tar.gz", archive.getvalue(), "application/gzip")},
            timeout=120,
        )
        if status == 401:
            if attempt == 3:
                die("Connector code is stale after 3 attempts. Generate a new connector from the dashboard and pull again.")
            time.sleep(2)
            continue
        if status < 200 or status >= 300:
            try:
                data = json.loads(payload.decode())
                die(data.get("error", f"Push failed with HTTP {status}."))
            except Exception:
                die(f"Push failed with HTTP {status}.")
        data = json.loads(payload.decode() or "{}")
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
    username = args.folder_name.strip().lower()
    connector_code = getpass.getpass("connector code: ").strip()
    target.mkdir(parents=True, exist_ok=False)

    server = args.server.rstrip("/")
    cfg, err = claim_binding(server, username, connector_code, target)
    if err:
        target.rmdir()
        die(err)
    data = cfg

    if cfg.get("last_tree_hash"):
        status, _, archive_bytes = api_request(
            f"{server}/sync/api/silicons/{username}/latest.tar.gz",
            headers={"X-Source-Token": cfg["source_token"]},
            timeout=120,
        )
        if status < 200 or status >= 300:
            target.rmdir()
            die(f"Snapshot download failed with HTTP {status}.")
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            tar.extractall(target)
        bootstrap_silicon_folder(target, cfg)
        print(f"Pulled {username} into {target}.")
    else:
        bootstrap_silicon_folder(target, cfg)
        print(f"Claimed {username} into {target}. No snapshot exists yet.")


def command_push(args):
    folder = current_dir()
    if args.subcommand == "now":
        push_once(folder, args.server.rstrip("/"))
        return

    print("Hourly sync started. Press Ctrl+C to stop.")
    while True:
        push_once(folder, args.server.rstrip("/"), quiet=False)
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
