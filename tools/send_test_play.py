import asyncio
import json
import base64
import time
import sys

sys.path.append('/root')
from bridge import glagol, ROUTER_IP, HTTP_PORT

async def run():
    ws = await glagol.connect()
    if not ws:
        print("Failed to connect to Glagol WS")
        return
    token = await glagol.get_token()

    stream_url = f"http://{ROUTER_IP}:{HTTP_PORT}/stream.wav?t=1"
    payload = {
        "stream": {
            "url": stream_url,
            "format": "MP3",
            "type": "FmRadio"
        },
        "metadata": {
            "title": "Test Spotify",
            "subtitle": "Alice 27"
        },
        "set_pause": False
    }
    proto = glagol.protobuf_dumps([
        (1, "audio_play"),
        (2, json.dumps(payload))
    ])
    b64 = base64.b64encode(proto).decode("ascii")
    cmd = {"command": "externalCommandBypass", "data": b64}
    msg_id = f"{int(time.time()*1000):032x}"
    msg = {
        "conversationToken": token,
        "id": msg_id,
        "sentTime": int(time.time() * 1000),
        "payload": cmd
    }
    await ws.send(json.dumps(msg))
    print(f"Sent audio_play for {stream_url}!")

    for i in range(5):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(raw)
            st = data.get("state", {})
            ps = st.get("playerState", {})
            print(f"Alice state {i+1}: playing={st.get('playing')}, playerType={ps.get('playerType')}, title={ps.get('title')}", flush=True)
        except asyncio.TimeoutError:
            print("No more messages")
            break

if __name__ == '__main__':
    asyncio.run(run())
