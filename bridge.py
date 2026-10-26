import argparse
import asyncio
import socket
import shutil
import base64
import collections
import glob
import json
import logging
import os
import re
import ssl
import struct
import sys
import time
import urllib.request
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("bridge")

def find_config_file():
    candidates = [
        os.environ.get("CONFIG_PATH"),
        "/root/config.json",
        "/mnt/usb/config.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        "config.json"
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

def get_default_local_ip(target_ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.1"

def list_yandex_devices(session_id):
    if not session_id:
        print("Error: session_id is empty! Please add session_id to config.json")
        return
    url = "https://quasar.yandex.ru/glagol/device_list"
    req = urllib.request.Request(url, headers={"Cookie": f"Session_id={session_id}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("\n=== YANDEX ALICE DEVICES FOUND ===")
            for d in data.get("devices", []):
                print(f"Name:     {d.get('name')}")
                print(f"ID:       {d.get('id')}")
                print(f"Platform: {d.get('platform')}")
                print("-" * 35)
    except Exception as e:
        print(f"Failed to fetch device list: {e}")

_config_file = find_config_file()
_config_data = {}
if _config_file:
    try:
        with open(_config_file, "r", encoding="utf-8") as f:
            _config_data = json.load(f)
        log.info(f"Loaded configuration from {_config_file}")
    except Exception as e:
        log.error(f"Error reading {_config_file}: {e}")
else:
    log.warning("No config.json found! Checking environment variables.")

_yandex = _config_data.get("yandex", {})
_server = _config_data.get("server", {})
_airplay = _config_data.get("airplay", {})
_audio = _config_data.get("audio", {})

SESSION_ID = _yandex.get("session_id", os.environ.get("SESSION_ID", ""))
DEVICE_ID = _yandex.get("device_id", os.environ.get("DEVICE_ID", ""))
PLATFORM = _yandex.get("platform", os.environ.get("PLATFORM", "yandexmini_2"))
STATION_IP = _yandex.get("station_ip", os.environ.get("STATION_IP", "192.168.1.102"))

_stream_host = _server.get("stream_host", os.environ.get("STREAM_HOST", "auto"))
if not _stream_host or _stream_host == "auto":
    ROUTER_IP = get_default_local_ip(STATION_IP)
else:
    ROUTER_IP = _stream_host

HTTP_PORT = int(_server.get("http_port", os.environ.get("HTTP_PORT", 8888)))
SOLOIST_WS = _server.get("soloist_ws", os.environ.get("SOLOIST_WS", "ws://127.0.0.1:9090"))
SOLOIST_BIN = _server.get("soloist_bin", shutil.which("soloist") or "/usr/local/bin/soloist")
SOLOIST_DATA = _server.get("soloist_data", os.environ.get("SOLOIST_DATA", "/root/soloist_data"))
if not os.path.exists(SOLOIST_DATA) and os.path.exists("./soloist_data"):
    SOLOIST_DATA = os.path.abspath("./soloist_data")
AIRPLAY_AUDIO_FIFO = _airplay.get("audio_fifo", os.environ.get("AIRPLAY_AUDIO_FIFO", "/tmp/shairport-sync-audio"))
AIRPLAY_META_FIFO = _airplay.get("meta_fifo", os.environ.get("AIRPLAY_META_FIFO", "/tmp/shairport-sync-metadata"))
PAUSE_DEBOUNCE_SEC = float(_audio.get("pause_debounce_sec", 1.0))

def get_pulse_server_env():
    """Finds active PulseAudio / PipeWire socket to ensure reliable client connection."""
    env = dict(os.environ)
    if "HOME" not in env:
        env["HOME"] = "/root"
    if "PULSE_SERVER" not in env:
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        uid = os.getuid() if hasattr(os, "getuid") else None
        candidates = []
        if xdg_runtime:
            candidates.append(os.path.join(xdg_runtime, "pulse", "native"))
        if uid is not None:
            candidates.append(f"/run/user/{uid}/pulse/native")
        candidates.extend(glob.glob("/tmp/pulse-*/native"))
        for sock in candidates:
            if os.path.exists(sock):
                env["PULSE_SERVER"] = f"unix:{sock}"
                break
    return env

def make_wav_header():
    """Generates standard 44-byte WAV header with 0x7FFFFFFF (positive signed max) for streaming."""
    data_size = 0x7FFFFFFF
    file_size = data_size + 36
    hdr = bytearray()
    hdr.extend(b'RIFF')
    hdr.extend(struct.pack('<I', file_size))
    hdr.extend(b'WAVE')
    hdr.extend(b'fmt ')
    hdr.extend(struct.pack('<I', 16))             # Subchunk1Size (16 for PCM)
    hdr.extend(struct.pack('<H', 1))              # AudioFormat (1 = PCM)
    hdr.extend(struct.pack('<H', 2))              # NumChannels (2)
    hdr.extend(struct.pack('<I', 44100))          # SampleRate (44.1 kHz bit-perfect with Spotify)
    hdr.extend(struct.pack('<I', 44100 * 2 * 2))  # ByteRate (176400 B/s = 1411.2 kbps lossless)
    hdr.extend(struct.pack('<H', 4))              # BlockAlign (4)
    hdr.extend(struct.pack('<H', 16))             # BitsPerSample (16-bit CD quality)
    hdr.extend(b'data')
    hdr.extend(struct.pack('<I', data_size))
    return bytes(hdr)

WAV_HEADER = make_wav_header()

class GlagolClient:
    def __init__(self):
        self.ws = None
        self.cached_token = None
        self.token_expiry = 0
        self.lock = asyncio.Lock()
        self.is_connected = False

    def _fetch_token_sync(self):
        url = f"https://quasar.yandex.ru/glagol/token?device_id={DEVICE_ID}&platform={PLATFORM}"
        req = urllib.request.Request(url, headers={"Cookie": f"Session_id={SESSION_ID}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data["token"]

    async def get_token(self):
        now = time.time()
        if self.cached_token and now < self.token_expiry:
            return self.cached_token
        try:
            loop = asyncio.get_running_loop()
            self.cached_token = await loop.run_in_executor(None, self._fetch_token_sync)
            self.token_expiry = time.time() + 1800
            log.info("Refreshed Yandex Glagol token (valid for 30 min)")
            return self.cached_token
        except Exception as e:
            log.warning(f"Failed to fetch Glagol token: {e}")
            if self.cached_token:
                return self.cached_token
            raise

    @staticmethod
    def protobuf_dumps(entries):
        buf = bytearray()
        for tag, val in entries:
            encoded = val.encode('utf-8')
            buf.append((tag << 3) | 2)
            length = len(encoded)
            while length > 127:
                buf.append((length & 0x7F) | 0x80)
                length >>= 7
            buf.append(length)
            buf.extend(encoded)
        return bytes(buf)

    async def connect(self):
        if self.ws and hasattr(self.ws, "closed") and not self.ws.closed:
            return self.ws

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        url = f"wss://{STATION_IP}:1961"
        self.ws = await websockets.connect(url, ssl=ssl_ctx, ping_interval=20, ping_timeout=10)
        self.is_connected = True
        return self.ws

    async def send_command(self, payload):
        async with self.lock:
            for attempt in range(2):
                try:
                    ws = await self.connect()
                    token = await self.get_token()
                    msg_id = f"{int(time.time()*1000):032x}"
                    msg = {
                        "conversationToken": token,
                        "id": msg_id,
                        "sentTime": int(time.time() * 1000),
                        "payload": payload
                    }
                    await ws.send(json.dumps(msg))
                    return True
                except Exception as e:
                    log.warning(f"Glagol send attempt {attempt+1} failed: {e}")
                    if self.ws:
                        try:
                            await self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
                    self.is_connected = False
                    await asyncio.sleep(0.3)
            return False

    async def audio_play(self, stream_url, title="Spotify", subtitle="Soloist", image_url=None):
        payload = {
            "stream": {
                "url": stream_url,
                "format": "MP3",
                "type": "FmRadio"
            },
            "metadata": {
                "title": title or "Spotify",
                "subtitle": subtitle or "Soloist"
            },
            "set_pause": False
        }
        if image_url:
            clean_img = image_url.replace("https://", "").replace("http://", "")
            payload["metadata"]["art_image_url"] = clean_img

        proto = self.protobuf_dumps([
            (1, "audio_play"),
            (2, json.dumps(payload))
        ])
        b64 = base64.b64encode(proto).decode('ascii')
        log.info(f"Sent audio_play: {title} - {subtitle} ({stream_url})")
        return await self.send_command({
            "command": "externalCommandBypass",
            "data": b64
        })

    async def stop(self):
        log.info("Sent stop to Alice")
        return await self.send_command({"command": "stop"})

    async def set_volume(self, volume):
        vol = round(max(0.0, min(1.0, float(volume))), 1)
        return await self.send_command({
            "command": "setVolume",
            "volume": vol
        })

    async def reader_loop(self):
        while True:
            try:
                ws = await self.connect()
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    st = data.get("state", {})
                    if "volume" in st:
                        alice_vol = round(float(st["volume"]), 1)
                        vol_coord.on_alice_volume(alice_vol)
            except Exception as e:
                self.ws = None
                self.is_connected = False
                await asyncio.sleep(2)

    async def ping_loop(self):
        """Protocol-level ping_interval=20 in websockets handles keepalive. Bogus application-level pings removed."""
        while True:
            await asyncio.sleep(3600)

glagol = GlagolClient()

class VolumeCoordinator:
    def __init__(self):
        self.last_target_vol = None
        self.last_sent_time = 0.0
        self.debounce_task = None

    def on_spotify_volume(self, vol_pct):
        target_step = max(0.0, min(1.0, round(vol_pct / 10.0) / 10.0))
        # If target volume hasn't changed meaningfully, do not send
        if self.last_target_vol is not None and abs(target_step - self.last_target_vol) < 0.05:
            return

        if self.debounce_task and not self.debounce_task.done():
            self.debounce_task.cancel()

        async def _delayed_send():
            try:
                await asyncio.sleep(0.2)
                self.last_target_vol = target_step
                self.last_sent_time = time.time()
                log.info(f"Syncing Spotify volume to Alice: {target_step} (Level {int(round(target_step * 10))})")
                await glagol.set_volume(target_step)
            except asyncio.CancelledError:
                pass

        self.debounce_task = asyncio.create_task(_delayed_send())

    def on_airplay_volume_db(self, db_val):
        """Maps AirPlay dB (-30.0 dB to 0.0 dB, -144 for mute) to Alice 0.0-1.0."""
        if db_val <= -30.0:
            target_vol = 0.0
        elif db_val >= 0.0:
            target_vol = 1.0
        else:
            target_vol = round((db_val + 30.0) / 30.0, 1)

        if self.last_target_vol is not None and abs(target_vol - self.last_target_vol) < 0.05:
            return

        if self.debounce_task and not self.debounce_task.done():
            self.debounce_task.cancel()

        async def _delayed_send():
            try:
                await asyncio.sleep(0.1)
                self.last_target_vol = target_vol
                self.last_sent_time = time.time()
                log.info(f"Syncing AirPlay volume {db_val:.1f} dB to Alice: {target_vol} (Level {int(round(target_vol * 10))})")
                await glagol.set_volume(target_vol)
            except asyncio.CancelledError:
                pass

        self.debounce_task = asyncio.create_task(_delayed_send())

    def on_alice_volume(self, alice_vol):
        now = time.time()
        # 3.0s cooldown after commanding volume to strictly prevent feedback loop
        if now - self.last_sent_time < 3.0:
            return
        # If Alice is reporting the volume we already commanded, ignore
        if self.last_target_vol is not None and abs(alice_vol - self.last_target_vol) < 0.05:
            return

        self.last_target_vol = alice_vol
        self.last_sent_time = now
        target_pct = int(round(alice_vol * 100))
        log.info(f"Physical volume on Alice changed to {alice_vol} -> syncing to Spotify: {target_pct}%")

        async def _set_vol():
            try:
                proc = await asyncio.create_subprocess_exec(
                    SOLOIST_BIN, "ctl", "-D", SOLOIST_DATA,
                    "volume", str(target_pct),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await proc.wait()
            except Exception:
                pass
        asyncio.create_task(_set_vol())

vol_coord = VolumeCoordinator()

# Bit-Perfect Lossless WAV AudioHub (1411.2 kbps PCM)
class AudioHub:
    def __init__(self):
        # Maps client_ip -> q (strictly one active stream per client IP)
        self.subscribers = {}
        self.running = False
        self.stream_token = 1
        # ~88 KB pre-buffer (~10 chunks * 8820 bytes = ~0.50s at 44.1kHz s16le stereo)
        self.recent_buffer = collections.deque(maxlen=10)

    @property
    def active_clients(self):
        return len(self.subscribers)

    def next_token(self):
        self.stream_token += 1
        return self.stream_token

    def get_recent_chunks(self):
        return list(self.recent_buffer)

    def register_client(self, client_ip, q):
        # Evict any stale previous connection from this exact IP
        if client_ip in self.subscribers:
            old_q = self.subscribers[client_ip]
            log.info(f"AudioHub: evicting stale connection for {client_ip}")
            try:
                old_q.put_nowait(None)
            except Exception:
                pass
        self.subscribers[client_ip] = q
        log.info(f"AudioHub: client {client_ip} registered (active={self.active_clients})")

    def unregister_client(self, client_ip, q):
        if self.subscribers.get(client_ip) == q:
            del self.subscribers[client_ip]
            log.info(f"AudioHub: client {client_ip} unregistered (active={self.active_clients})")

    def clear_buffer(self):
        self.recent_buffer.clear()

    def flush_queues(self):
        pass

    def disconnect_all(self):
        if self.subscribers:
            log.info(f"AudioHub: disconnecting all subscribers (count={len(self.subscribers)})")
            for ip, q in list(self.subscribers.items()):
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
            self.subscribers.clear()
        self.recent_buffer.clear()

    async def run(self):
        self.running = True
        log.info("AudioHub Lossless WAV pipeline starting (44.1kHz 16-bit stereo PCM, 50ms chunks)...")

        CHUNK_SIZE = 8820  # 50 ms of audio (2205 frames * 4 bytes)
        while self.running:
            p_parec = None
            try:
                env = get_pulse_server_env()
                p_parec = await asyncio.create_subprocess_exec(
                    "parec", "-d", "auto_null.monitor",
                    "--rate=44100", "--channels=2", "--format=s16le",
                    "--latency-msec=50", "--process-time-msec=20",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env
                )

                while self.running:
                    raw = await p_parec.stdout.readexactly(CHUNK_SIZE)
                    if not raw:
                        break

                    self.recent_buffer.append(raw)
                    for ip, q in list(self.subscribers.items()):
                        try:
                            q.put_nowait(raw)
                        except asyncio.QueueFull:
                            log.warning(f"AudioHub: buffer overflow for {ip} (>5s), dropping stale connection")
                            try:
                                q.put_nowait(None)
                            except Exception:
                                pass
                            self.subscribers.pop(ip, None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"AudioHub parec error: {e}")
            finally:
                if p_parec:
                    try:
                        p_parec.kill()
                        await p_parec.wait()
                    except Exception:
                        pass
                await asyncio.sleep(0.5)

hub = AudioHub()

# AirPlay Stream Manager
class AirPlayManager:
    def __init__(self, fifo_path=AIRPLAY_AUDIO_FIFO):
        self.fifo_path = fifo_path
        self.proc = None
        self.worker_task = None

    def is_streaming(self):
        return self.worker_task is not None and not self.worker_task.done()

    def start_streaming(self):
        self.stop_streaming()
        self.worker_task = asyncio.create_task(self._feed_worker())

    def stop_streaming(self):
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            self.worker_task = None
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
        log.info("AirPlay Manager: streaming stopped")

    async def _feed_worker(self):
        loop = asyncio.get_running_loop()
        cmd = [
            "pacat", "--playback", "-d", "auto_null",
            "--rate=44100", "--channels=2", "--format=s16le",
            "--latency-msec=50", "--process-time-msec=20"
        ]
        f = None
        try:
            if not os.path.exists(self.fifo_path):
                os.mkfifo(self.fifo_path)
        except Exception:
            pass

        try:
            fd = os.open(self.fifo_path, os.O_RDONLY | os.O_NONBLOCK)
            f = open(fd, "rb", buffering=0)
            log.info("AirPlay Manager: FIFO opened. Spawning pacat forwarder...")

            env = get_pulse_server_env()
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                env=env
            )

            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, f)

            total_bytes = 0
            last_logged = 0

            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                self.proc.stdin.write(chunk)
                await self.proc.stdin.drain()
                total_bytes += len(chunk)
                if total_bytes - last_logged >= 500000:
                    log.info(f"AirPlay Audio: streamed {total_bytes // 1024} KB to PulseAudio")
                    last_logged = total_bytes
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning(f"AirPlay feed worker error: {e}")
        finally:
            if self.proc:
                try:
                    if self.proc.stdin:
                        self.proc.stdin.close()
                    self.proc.terminate()
                    await self.proc.wait()
                except Exception:
                    pass
                self.proc = None
            if f:
                try:
                    f.close()
                except Exception:
                    pass
            log.info("AirPlay Manager: pacat process terminated and cleaned up")

airplay_mgr = AirPlayManager()

# Coordinator state
class State:
    def __init__(self):
        self.desired_playing = False
        self.airplay_playing = False
        self.alice_playing = False
        self.last_title = "Spotify Track"
        self.last_artist = "Spotify"
        self.last_img = None
        self.airplay_title = "AirPlay 2"
        self.airplay_artist = "Apple Device"
        self.last_command_time = 0.0
        self.pause_task = None

state = State()

async def client_handler(reader, writer):
    q = None
    total = 0
    try:
        req_line = await reader.readline()
        if not req_line:
            writer.close()
            return
        
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break

        req_str = req_line.decode('latin1', errors='ignore').strip()
        is_head = req_str.startswith("HEAD")
        log.info(f"Alice HTTP connection: {req_str}")

        if "/airplay/play" in req_str:
            log.info("AirPlay 2: play request received -> taking over from Spotify")
            state.airplay_playing = True
            state.desired_playing = False
            pause_proc = await asyncio.create_subprocess_exec(
                SOLOIST_BIN, "ctl", "-D", SOLOIST_DATA, "pause",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await pause_proc.wait()

            if state.pause_task and not state.pause_task.done():
                state.pause_task.cancel()
                state.pause_task = None

            now = time.time()
            state.last_command_time = now
            state.alice_playing = True
            hub.clear_buffer()
            airplay_mgr.start_streaming()

            token = hub.next_token()
            stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t={token}"
            await glagol.audio_play(stream_url, state.airplay_title, state.airplay_artist, None)
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        if "/airplay/stop" in req_str:
            log.info("AirPlay 2: stop request received")
            state.airplay_playing = False
            state.desired_playing = False
            state.alice_playing = False
            airplay_mgr.stop_streaming()
            hub.clear_buffer()
            hub.disconnect_all()
            await glagol.stop()
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        if "/airplay/volume" in req_str:
            match = re.search(r"[?&]vol=([-0-9.]+)", req_str)
            if match:
                try:
                    db_val = float(match.group(1))
                    vol_coord.on_airplay_volume_db(db_val)
                except ValueError:
                    pass
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        client_ip = writer.get_extra_info('peername')[0] if writer.get_extra_info('peername') else "unknown"

        # Check stream token: /stream.wav?t=123
        match = re.search(r"[?&]t=([0-9]+)", req_str)
        req_token = int(match.group(1)) if match else 0
        if req_token != hub.stream_token:
            log.warning(f"HTTP: rejected stale token {req_token} (current: {hub.stream_token}) from {client_ip}")
            writer.write(b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        resp = (
            f"HTTP/1.0 200 OK\r\n"
            f"Content-Type: audio/wav\r\n"
            f"Server: Icecast 2.4.4\r\n"
            f"icy-name: Spotify Live Lossless WAV\r\n"
            f"Pragma: no-cache\r\n"
            f"Cache-Control: no-cache\r\n"
            f"Connection: close\r\n\r\n"
        ).encode('utf-8')
        writer.write(resp)
        await writer.drain()

        if is_head:
            writer.close()
            await writer.wait_closed()
            return

        # Send WAV header
        writer.write(WAV_HEADER)
        await writer.drain()

        # Prime GStreamer pre-roll buffer with ~0.5s of WAV audio (~10 chunks * 8820 bytes)
        burst_chunks = hub.get_recent_chunks()
        for chunk in burst_chunks:
            writer.write(chunk)
        if burst_chunks:
            await writer.drain()

        # 100 chunks cushion (~5s at 50ms per chunk)
        q = asyncio.Queue(maxsize=100)
        hub.register_client(client_ip, q)
        state.alice_playing = True
        total = len(WAV_HEADER) + sum(len(c) for c in burst_chunks)

        while True:
            chunk = await q.get()
            if chunk is None:
                log.info(f"AudioHub: stream connection for {client_ip} cleanly evicted/closed")
                break
            writer.write(chunk)
            await writer.drain()
            total += len(chunk)

    except (ConnectionResetError, ConnectionError, BrokenPipeError):
        pass
    except Exception as e:
        log.warning(f"Client connection error ({client_ip}): {e}")
    finally:
        if q:
            hub.unregister_client(client_ip, q)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info(f"Alice HTTP connection closed ({client_ip}, total bytes={total})")

def extract_track_info(item):
    if not item:
        return "Spotify Track", "Spotify", None
    decorations = item.get("decorations", {})
    title = decorations.get("identity", {}).get("name", "Spotify Track")
    creators = item.get("creators", [])
    artists = ", ".join(
        c.get("decorations", {}).get("identity", {}).get("name", "")
        for c in creators
        if c.get("decorations", {}).get("identity", {}).get("name")
    ) or "Spotify"
    covers = item.get("visual_identity", {}).get("cover", [])
    img_url = covers[0].get("url") if covers else None
    return title, artists, img_url

async def delayed_stop():
    try:
        await asyncio.sleep(PAUSE_DEBOUNCE_SEC)
        if not state.desired_playing and not state.airplay_playing:
            log.info("Pause: stopping Alice speaker immediately")
            state.alice_playing = False
            hub.disconnect_all()
            await glagol.stop()
    except asyncio.CancelledError:
        pass

async def watchdog():
    while True:
        try:
            await asyncio.sleep(2.0)
            now = time.time()
            if state.airplay_playing:
                if (not state.alice_playing or hub.active_clients == 0) and (now - state.last_command_time >= 3.0):
                    token = hub.next_token()
                    stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t={token}"
                    log.warning(f"Watchdog: AirPlay active but Alice not receiving. Re-dispatching audio_play (token={token})...")
                    state.last_command_time = now
                    state.alice_playing = True
                    await glagol.audio_play(stream_url, state.airplay_title, state.airplay_artist, None)
            elif state.desired_playing:
                if (not state.alice_playing or hub.active_clients == 0) and (now - state.last_command_time >= 3.0):
                    token = hub.next_token()
                    stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t={token}"
                    log.warning(f"Watchdog: Spotify playing but Alice not active. Dispatching audio_play (token={token})...")
                    state.last_command_time = now
                    state.alice_playing = True
                    await glagol.audio_play(stream_url, state.last_title, state.last_artist, state.last_img)
        except Exception as e:
            log.warning(f"Watchdog error: {e}")

async def soloist_monitor():
    while True:
        try:
            log.info(f"Connecting to Soloist WS at {SOLOIST_WS}...")
            async with websockets.connect(SOLOIST_WS) as ws:
                log.info("Soloist WS connected!")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    msg_type = data.get("type")

                    if msg_type == "auth_state":
                        if data.get("logged_in"):
                            log.info("Spotify Connect: authenticated")

                    elif msg_type == "track_changed":
                        item = data.get("item", {})
                        state.last_title, state.last_artist, state.last_img = extract_track_info(item)
                        log.info(f"Track changed: {state.last_title} - {state.last_artist}")
                        if state.desired_playing and hub.active_clients > 0:
                            token = hub.next_token()
                            stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t={token}"
                            log.info(f"Glagol: updating track (token={token}): {state.last_title} - {state.last_artist}")
                            await glagol.audio_play(stream_url, state.last_title, state.last_artist, state.last_img)

                    elif msg_type in ("playback_changed", "playback_state"):
                        status = data.get("status", "")
                        item = data.get("item")
                        if item:
                            state.last_title, state.last_artist, state.last_img = extract_track_info(item)

                        if status == "playing":
                            if state.airplay_playing:
                                log.info("Soloist: Spotify started -> taking over from AirPlay")
                                state.airplay_playing = False
                                airplay_mgr.stop_streaming()

                            state.desired_playing = True
                            if state.pause_task and not state.pause_task.done():
                                state.pause_task.cancel()
                                state.pause_task = None

                            if not state.alice_playing or hub.active_clients == 0:
                                now = time.time()
                                if now - state.last_command_time >= 1.0:
                                    token = hub.next_token()
                                    stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t={token}"
                                    log.info(f"PLAY: Starting Alice stream (token={token}): {state.last_title} - {state.last_artist}")
                                    state.last_command_time = now
                                    state.alice_playing = True
                                    hub.clear_buffer()
                                    await glagol.audio_play(stream_url, state.last_title, state.last_artist, state.last_img)

                        elif status in ("paused", "stopped"):
                            if state.desired_playing:
                                state.desired_playing = False
                                if state.pause_task and not state.pause_task.done():
                                    state.pause_task.cancel()
                                state.pause_task = asyncio.create_task(delayed_stop())

                    elif msg_type in ("volume", "volume_changed"):
                        vol = int(data.get("volume", 50))
                        vol_coord.on_spotify_volume(vol)

        except Exception as e:
            log.warning(f"Soloist WS error: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

async def airplay_metadata_listener():
    """Reads metadata pipe from shairport-sync to update title and artist on Alice."""
    fifo_path = AIRPLAY_META_FIFO
    while True:
        f = None
        try:
            if not os.path.exists(fifo_path):
                await asyncio.sleep(2)
                continue

            loop = asyncio.get_running_loop()
            fd = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
            f = open(fd, "rb", buffering=0)

            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, f)

            buf = ""
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    break
                buf += chunk.decode('latin1', errors='ignore')
                while "</item>" in buf:
                    item_str, buf = buf.split("</item>", 1)
                    code_m = re.search(r"<code>([0-9a-fA-F]+)</code>", item_str)
                    data_m = re.search(r"<data encoding=\"base64\">([^<]*)</data>", item_str)
                    if code_m and data_m:
                        code_hex = code_m.group(1).lower()
                        b64_val = data_m.group(1).strip()
                        try:
                            decoded = base64.b64decode(b64_val).decode('utf-8', errors='ignore').strip()
                            if code_hex == "6d696e6d" and decoded:
                                state.airplay_title = decoded
                                log.info(f"AirPlay Track: {state.airplay_title}")
                            elif code_hex == "61736172" and decoded:
                                state.airplay_artist = decoded
                                log.info(f"AirPlay Artist: {state.airplay_artist}")
                        except Exception:
                            pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.debug(f"AirPlay metadata error: {e}")
            await asyncio.sleep(2)
        finally:
            if f:
                try:
                    f.close()
                except Exception:
                    pass

async def main():
    # Calibrate PulseAudio null sink to 85% (-2.5 dB headroom) to prevent 0 dBFS clipping/wrapping
    try:
        env = get_pulse_server_env()
        vol_proc = await asyncio.create_subprocess_exec(
            "pactl", "set-sink-volume", "auto_null", "85%",
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await vol_proc.wait()
        log.info("PulseAudio auto_null sink calibrated with -2.5 dB headroom (85%)")
    except Exception as e:
        log.warning(f"Could not calibrate auto_null headroom: {e}")

    hub_task = asyncio.create_task(hub.run())
    server = await asyncio.start_server(client_handler, "0.0.0.0", HTTP_PORT)
    log.info(f"Ultra-low-latency Lossless WAV (1411 kbps) Server listening on {HTTP_PORT}")

    monitor_task = asyncio.create_task(soloist_monitor())
    watchdog_task = asyncio.create_task(watchdog())
    reader_task = asyncio.create_task(glagol.reader_loop())
    ping_task = asyncio.create_task(glagol.ping_loop())
    meta_task = asyncio.create_task(airplay_metadata_listener())

    async with server:
        await asyncio.gather(
            hub_task,
            monitor_task,
            watchdog_task,
            reader_task,
            ping_task,
            meta_task,
            server.serve_forever()
        )

if __name__ == "__main__":
    if "--list-devices" in sys.argv or "--discover" in sys.argv:
        list_yandex_devices(SESSION_ID)
        sys.exit(0)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
