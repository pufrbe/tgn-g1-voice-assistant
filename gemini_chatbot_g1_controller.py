#!/usr/bin/env python3
import asyncio
import time
import socket

import pyaudio
import math
from scipy import signal
from google import genai
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
from unitree_sdk2py.idl.unitree_go.msg.dds_._WirelessController_ import WirelessController_
import numpy as np
import struct



# ---- Your known-good devices ----
IN_DEV = 24     # ReSpeaker 4 Mic Array
#OUT_DEV = 26    # pulse (routes to default BT sink)


# ---- Audio ----
FORMAT = pyaudio.paInt16
CHANNELS = 1
MIC_RATE = 16000
#OUT_RATE = 24000
CHUNK = 1024  # ~64ms at 16kHz

MCAST_PORT=5555
MCAST_GRP="239.168.123.161"

# ---- Gemini Live ----

model = "gemini-2.5-flash-native-audio-preview-12-2025"
tools = [{'google_search': {}}]

config = {
    "response_modalities": ["AUDIO"],
    "tools": tools,
    # optional but very helpful for debugging:
    "output_audio_transcription": {},
    "system_instruction": "You are a helpful voice assistant for Argentine gas transportation company TGN. Reply concisely and in spanish.",
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Algenib",
            }
        }
    },
    # "system_instruction":"For factual or time-sensitive questions, use Google Search before answering. "
    # "If you did not use Search, say 'not searched'. Keep answers concise.",
}

IN_RATE = 24000
OUT_RATE = 16000
CHUNK_SIZE = 96000
DT = 1

pya = pyaudio.PyAudio()
client = genai.Client()

net_if = "eth0"

ChannelFactoryInitialize(0, net_if)
audioClient = AudioClient()
audioClient.SetTimeout(10.0)
audioClient.Init()

controller_input_event = asyncio.Event()
#loop = asyncio.get_event_loop()
button_pressed = False

def callback(msg: WirelessController_):
    global button_pressed
    if msg.keys == 512:
        button_pressed = True
    else:
        button_pressed = False
        print("button_unpressed")

sub = ChannelSubscriber("rt/wirelesscontroller", WirelessController_)
sub.Init(callback, 1)

def array_resample(array : bytearray, in_rate : int, out_rate : int):
    factor = math.gcd(in_rate, out_rate)
    up = out_rate//factor
    down = in_rate//factor
    x = np.frombuffer(array, dtype=np.int16).astype(np.float32)
    y = signal.resample_poly(x, up, down)

    data = np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    return data



def play_pcm_stream(client, pcm_list, stream_name="example", chunk_size=96000, sleep_time=1.0, verbose=False, out_rate=16000):
    """
    Play PCM audio stream (16-bit little-endian format), sending data in chunks.

    Parameters:
        client: An object with a PlayStream method
        pcm_list: list[int], PCM audio data in int16 format
        stream_name: Stream name, default is "example"
        chunk_size: Number of bytes to send per chunk, default is 96000 (3 seconds at 16kHz)
        sleep_time: Delay between chunks in seconds
    """
    pcm_data = bytes(pcm_list)
    stream_id = str(2093840)  # Unique stream ID based on current timestamp
    offset = 0
    chunk_index = 0
    total_size = len(pcm_data)
    print(f"total_size: {total_size}")

    while offset < total_size:
        x0 = time.time()
        remaining = total_size - offset
        current_chunk_size = min(chunk_size, remaining)
        chunk = pcm_data[offset:offset + current_chunk_size]

        sleep_time = current_chunk_size/out_rate/2
        #print(f"sleep time: {sleep_time}")
        if verbose:
            # Print info about the current chunk
            print(f"[CHUNK {chunk_index}] offset = {offset}, size = {current_chunk_size} bytes")
            print("  First 10 samples (int16): ", end="")
            for i in range(0, min(20, len(chunk) - 1), 2):
                sample = struct.unpack_from('<h', chunk, i)[0]
                print(sample, end=" ")
            print()

        # Send the chunk
        ret_code, _ = client.PlayStream(stream_name, stream_id, chunk)
        if ret_code != 0:
            print(f"[ERROR] Failed to send chunk {chunk_index}, return code: {ret_code}")
            break
        else:
            print(f"[INFO] Chunk {chunk_index} sent successfully")

        offset += current_chunk_size
        chunk_index += 1
        x0 = time.time() - x0
        #time.sleep(max(sleep_time-x0,0))

def silence_chunk() -> bytes:
    return b"\x00\x00" * CHUNK

async def wait_line(prompt: str = "") -> str:
    return (await asyncio.to_thread(input, prompt)).strip()

async def record_until_enter(max_seconds: float = 30.0) -> list[bytes]:
    """Record mic until user presses ENTER again."""
    loop = asyncio.get_running_loop()
    global button_pressed

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", MCAST_PORT))

    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton("192.168.123.164"))

    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    #sock.setblocking(False)
    #sock.settimeout(2.0)

    frames: list[bytes] = []
    print("[REC] Recording... press ENTER to stop and send.")
    #stop_task = asyncio.create_task(asyncio.to_thread(input))
    #stop_task = asyncio.create_task(controller_input_event.wait())
    t0 = time.time()

    try:
        while True:
            timeout = max_seconds - (time.time() - t0)
            if timeout <= 0:
                print("[REC] Max record time reached; sending.")
                break

            recv_task = asyncio.create_task(loop.sock_recvfrom(sock, CHUNK))

            done, pending = await asyncio.wait(
                {recv_task},
                timeout=timeout
            )
            print(button_pressed)

            #if stop_task in done:
            if button_pressed == False:
                for p in pending:
                    p.cancel()
                break

            if recv_task in done:
                data, _ = recv_task.result()
                frames.append(data)
    finally:
        sock.close()



    # small silence tail to help VAD infer end-of-speech
    frames.extend([silence_chunk()] * 6)
    return frames

async def play_reply_streaming(session):
    """Receive ONE model turn and play audio as it arrives (plus print transcript + tool debug)."""
    """
    out_stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=OUT_RATE,
        output=True,
        output_device_index=OUT_DEV,
        frames_per_buffer=CHUNK,
    )
    """

    try:
        turn = session.receive()
        got_audio = False
        saw_tooling = False
        print(turn)
        array = bytearray([])
        chunk_accum = 0
        async for resp in turn:

            sc = getattr(resp, "server_content", None)

            print(sc)
            if not sc:
                continue

            # Print model audio transcription (you enabled output_audio_transcription) :contentReference[oaicite:3]{index=3}
            ot = getattr(sc, "output_transcription", None)
            if ot and getattr(ot, "text", None):
                print("[model transcript]", ot.text)

            # If Search/tooling happens, Gemini 2.5 may emit executable_code / code_execution_result :contentReference[oaicite:4]{index=4}
            mt = getattr(sc, "model_turn", None)
            if mt:
                for part in mt.parts:
                    if getattr(part, "executable_code", None) is not None:
                        saw_tooling = True
                        print("[tool executable_code]\n", part.executable_code.code)
                    if getattr(part, "code_execution_result", None) is not None:
                        saw_tooling = True
                        print("[tool code_execution_result]\n", part.code_execution_result.output)

                    inline = getattr(part, "inline_data", None)

                    if inline and isinstance(inline.data, (bytes, bytearray)):
                        got_audio = True
                        #await asyncio.to_thread(
                        array.extend(bytes(inline.data))
                        chunk_accum += len(inline.data)

            if chunk_accum > 72000:
                resampled = array_resample(array, IN_RATE, OUT_RATE)
                play_pcm_stream(audioClient, resampled, chunk_size = CHUNK_SIZE, sleep_time = DT)
                chunk_accum = 0
                array = bytearray([])

            if getattr(sc, "turn_complete", False):
                resampled = array_resample(array, IN_RATE, OUT_RATE)
                play_pcm_stream(audioClient, resampled, chunk_size = CHUNK_SIZE, sleep_time = DT)
                break

        if not got_audio:
            print("[WARN] No audio reply received.")

        if not saw_tooling:
            print("[INFO] No tool/code-execution observed this turn (likely answered without Search).")

    finally:
        pass
        #out_stream.stop_stream()
        #out_stream.close()


async def send_one_turn(session, frames: list[bytes]):
    """
    Send one utterance to the *same* live session.
    We pace chunks roughly in real-time so VAD behaves more reliably.
    """
    chunk_secs = CHUNK / MIC_RATE  # ~0.064s
    for ch in frames:
        print("estoy enviando")
        await session.send_realtime_input(audio={"data": ch, "mime_type": f"audio/pcm;rate={MIC_RATE}"})
        await asyncio.sleep(chunk_secs)  # helps VAD / turn-taking consistency


async def main():
    print(f"Mic device {IN_DEV} @ {MIC_RATE} Hz")
    #print(f"Output device {OUT_DEV} (pulse) @ {OUT_RATE} Hz")
    print("Controls:")
    print("  ENTER       -> start recording")
    print("  ENTER       -> stop and send")
    print("  q + ENTER   -> quit\n")

    async with client.aio.live.connect(model=model, config=config) as session:
        while True:
            #cmd = await wait_line("Ready. Press ENTER to record (or q to quit): ")
            #if cmd.lower() == "q":
            #    break
            if not button_pressed:
                await asyncio.sleep(0.05)
                continue

            print("grabando?")
            frames = await record_until_enter(max_seconds=30.0)
            if len(frames) <= 6:
                print("[INFO] Too short; try again.\n")
                continue

            print("[Gemini] replying...")
            await send_one_turn(session, frames)
            await play_reply_streaming(session)
            print()

    pya.terminate()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass