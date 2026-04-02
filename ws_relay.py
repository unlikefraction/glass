#!/usr/bin/env python3
"""Glass WebSocket Relay — thin real-time pipe between agents and browsers."""

import asyncio
import json
import logging
import os
import signal
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "glasssite.settings")
django.setup()

import websockets  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Carbon  # noqa: E402
from syncer.models import Silicon  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[ws-relay] %(message)s")
log = logging.getLogger("ws-relay")

HOST = "127.0.0.1"
PORT = int(os.environ.get("WS_RELAY_PORT", "8001"))
HEARTBEAT_DB_INTERVAL = 15  # seconds between DB writes for REST compat

# ── Room registry ────────────────────────────────────────────

ROOMS = {}  # {silicon_username: {"agent": ws|None, "browsers": set()}}


def get_room(username):
    if username not in ROOMS:
        ROOMS[username] = {"agent": None, "browsers": set()}
    return ROOMS[username]


async def broadcast_to_browsers(username, message):
    room = ROOMS.get(username)
    if not room:
        return
    dead = set()
    for ws in room["browsers"]:
        try:
            await ws.send(message)
        except Exception:
            dead.add(ws)
    room["browsers"] -= dead


async def send_to_agent(username, message):
    room = ROOMS.get(username)
    if not room or not room["agent"]:
        return False
    try:
        await room["agent"].send(message)
        return True
    except Exception:
        room["agent"] = None
        return False


# ── Auth helpers (run in thread to avoid blocking asyncio) ───


def _auth_agent_sync(token):
    """Validate agent Bearer token. Returns Silicon or None."""
    try:
        return Silicon.objects.get(api_key=token, is_active=True)
    except Silicon.DoesNotExist:
        return None


def _auth_browser_sync(session_key, username):
    """Validate browser session owns the silicon. Returns True/False."""
    try:
        store = SessionStore(session_key=session_key)
        carbon_id = store.get("carbon_id")
        if not carbon_id:
            return False
        return Silicon.objects.filter(
            username=username, owner_id=carbon_id, is_active=True
        ).exists()
    except Exception:
        return False


def _update_heartbeat_sync(username, status):
    """Update Silicon heartbeat in DB for REST API compatibility."""
    try:
        Silicon.objects.filter(username=username).update(
            last_heartbeat=timezone.now(),
            reported_status=status,
        )
    except Exception:
        pass


# ── Agent handler ────────────────────────────────────────────


async def handle_agent(ws):
    """Handle agent WebSocket connection."""
    silicon_username = None
    try:
        # Wait for auth message (5s timeout)
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not msg.get("token"):
            await ws.send(json.dumps({"type": "auth_error", "reason": "Expected auth message"}))
            return

        silicon = await asyncio.to_thread(_auth_agent_sync, msg["token"])
        if not silicon:
            await ws.send(json.dumps({"type": "auth_error", "reason": "Invalid token"}))
            return

        silicon_username = silicon.username
        room = get_room(silicon_username)

        # Close old agent connection if any
        if room["agent"]:
            try:
                await room["agent"].close(1000, "replaced")
            except Exception:
                pass
        room["agent"] = ws

        await ws.send(json.dumps({"type": "auth_ok", "silicon": silicon_username}))
        log.info(f"Agent connected: {silicon_username}")

        # Notify browsers
        await broadcast_to_browsers(
            silicon_username,
            json.dumps({"type": "agent_status", "connected": True}),
        )

        last_db_update = 0

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                # Relay to browsers
                await broadcast_to_browsers(silicon_username, raw)
                # Periodically update DB for REST compat
                now = asyncio.get_event_loop().time()
                if now - last_db_update > HEARTBEAT_DB_INTERVAL:
                    status = msg.get("status", "")
                    await asyncio.to_thread(_update_heartbeat_sync, silicon_username, status)
                    last_db_update = now

            elif msg_type in ("log", "command_ack", "command_result"):
                # Relay to browsers as-is
                await broadcast_to_browsers(silicon_username, raw)

    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        pass
    except Exception as e:
        log.error(f"Agent error ({silicon_username}): {e}")
    finally:
        if silicon_username:
            room = ROOMS.get(silicon_username)
            if room and room["agent"] is ws:
                room["agent"] = None
                log.info(f"Agent disconnected: {silicon_username}")
                await broadcast_to_browsers(
                    silicon_username,
                    json.dumps({"type": "agent_status", "connected": False}),
                )


# ── Browser handler ──────────────────────────────────────────


async def handle_browser(ws, username):
    """Handle browser WebSocket connection."""
    try:
        # Auth via session cookie
        cookies = {}
        cookie_header = ws.request.headers.get("Cookie", "")
        for item in cookie_header.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k.strip()] = v.strip()

        session_key = cookies.get("sessionid", "")
        if not session_key:
            await ws.send(json.dumps({"type": "auth_error", "reason": "No session"}))
            return

        ok = await asyncio.to_thread(_auth_browser_sync, session_key, username)
        if not ok:
            await ws.send(json.dumps({"type": "auth_error", "reason": "Not authorized"}))
            return

        room = get_room(username)
        room["browsers"].add(ws)
        await ws.send(json.dumps({"type": "auth_ok"}))

        # Send current agent status
        agent_connected = room["agent"] is not None
        await ws.send(json.dumps({"type": "agent_status", "connected": agent_connected}))

        log.info(f"Browser connected: {username} ({len(room['browsers'])} tabs)")

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "command":
                cmd = msg.get("command", "")
                if cmd in ("start", "stop", "restart"):
                    # Add ID and relay to agent
                    msg["id"] = str(uuid.uuid4())[:8]
                    sent = await send_to_agent(username, json.dumps(msg))
                    if not sent:
                        await ws.send(json.dumps({
                            "type": "command_result",
                            "id": msg["id"],
                            "status": "failed",
                            "message": "Agent not connected",
                        }))

    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        log.error(f"Browser error ({username}): {e}")
    finally:
        room = ROOMS.get(username)
        if room:
            room["browsers"].discard(ws)
            log.info(f"Browser disconnected: {username} ({len(room['browsers'])} tabs)")


# ── Router ───────────────────────────────────────────────────


async def router(ws):
    """Route WebSocket connections by path."""
    path = ws.request.path

    if path == "/ws/agent/":
        await handle_agent(ws)
    elif path.startswith("/ws/control/") and path.endswith("/"):
        username = path[len("/ws/control/"):-1]
        if username:
            await handle_browser(ws, username)
        else:
            await ws.close(1008, "Missing username")
    else:
        await ws.close(1008, "Unknown path")


# ── Main ─────────────────────────────────────────────────────


async def main():
    stop = asyncio.get_event_loop().create_future()

    def handle_signal():
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    async with websockets.serve(router, HOST, PORT, ping_interval=20, ping_timeout=10):
        log.info(f"WebSocket relay listening on {HOST}:{PORT}")
        await stop

    log.info("Shutting down")


if __name__ == "__main__":
    asyncio.run(main())
