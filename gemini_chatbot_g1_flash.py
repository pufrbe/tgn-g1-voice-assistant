#!/usr/bin/env python3
import asyncio
import time
import socket

import math
from scipy import signal
from google import genai
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
import numpy as np
import struct
import json
import sys
sys.path.append("./vendor")
from vosk import Model, KaldiRecognizer

# ---- Audio ----
MIC_RATE = 16000
CHUNK = 5120

MCAST_PORT=5555
MCAST_GRP="239.168.123.161"

# ---- Gemini Live ----
model = "gemini-2.5-flash-native-audio-preview-12-2025"
tools = [{'google_search': {}}]

with open('prompt.txt', 'r') as file:
    prompt = file.read()

config = {
    "response_modalities": ["AUDIO"],
    "tools": tools,
    "output_audio_transcription": {},
    "system_instruction": prompt,
    "thinking_config":{"thinking_budget": 0},
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Puck",
            }
        }
    },
}


IN_RATE = 24000
OUT_RATE = 16000
CHUNK_SIZE = 96000
DT = 1

client = genai.Client()

# ---- Concurrence ----
queue = asyncio.Queue(0)
turn_complete = asyncio.Event()
answering = asyncio.Event()

# ---- STT ----
VOSK_MODEL_PATH = "vosk-model-small-es-0.42"

vosk_model = Model(VOSK_MODEL_PATH)
recognizer = KaldiRecognizer(vosk_model, MIC_RATE)
WAKE_WORD = "robot"
END_WORD = "gracias"

# ---- Unitree client ----
net_if = "eth0"
ChannelFactoryInitialize(0, net_if)
audioClient = AudioClient()
audioClient.SetTimeout(10.0)
audioClient.Init()

def array_resample(array : bytearray, in_rate : int, out_rate : int):
    factor = math.gcd(in_rate, out_rate)
    up = out_rate//factor
    down = in_rate//factor
    x = np.frombuffer(array, dtype=np.int16).astype(np.float32)
    y = signal.resample_poly(x, up, down)

    data = np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    return data

def play_pcm_stream(client, pcm_list, stream_id, stream_name="example", chunk_size=96000, sleep_time=1.0, verbose=False, out_rate=16000):
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
    stream_id = str(stream_id)
    offset = 0
    chunk_index = 0
    total_size = len(pcm_data)

    while offset < total_size:
        remaining = total_size - offset
        current_chunk_size = min(chunk_size, remaining)
        chunk = pcm_data[offset:offset + current_chunk_size]

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

        offset += current_chunk_size
        chunk_index += 1

def stop_pcm_stream(client, stream_name: str ="example"):
    client.PlayStop(stream_name)

def silence_chunk() -> bytes:
    return b"\x00\x00" * CHUNK

async def wait_for_wakeword(sock, wake_word: str = "robot", timeout=60.0):
    """
    Waits for wake_word using Vosk STT, for a time = timeout
    """
    loop = asyncio.get_running_loop()

    frames: list[bytes] = []

    print("[WAKE] Esperando llamada")

    while True:
        recv_task = asyncio.create_task(loop.sock_recvfrom(sock, CHUNK))

        done, _ = await asyncio.wait(
            {recv_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if recv_task in done:
            data, _ = recv_task.result()
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "")

            if text:
                print("[WAKE] se detecto la palabra " + text)
                if wake_word in text.split():
                    print("[WAKE] Wake word detectada")
                    recognizer.Reset()
                    return


async def record_until_silence(sock, max_seconds: float = 30.0, end_word: str = "adios", timeout = 60.0, threshold = 0.002, silence_duration = 3.0) -> list[bytes]:
    """Record mic until user stops speaking."""
    loop = asyncio.get_running_loop()

    frames: list[bytes] = []
    print("[REC] Recording...")
    t0 = time.time()
    end = False
    while True:
        audioClient.LedControl(255, 255, 0)
        timeout = max_seconds - (time.time() - t0)
        if timeout <= 0:
            print("[REC] Max record time reached; sending.")
            break

        recv_task = asyncio.create_task(loop.sock_recvfrom(sock, CHUNK))

        done, _ = await asyncio.wait(
            {recv_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if recv_task in done:
            data, _ = recv_task.result()
            #frames.append(data)    
            await queue.put(data)
        
                        
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "")
            if text and time.time() - t0 > 1.0:
                recognizer.Reset()
                if end_word in text.split():
                    end = True
                
        
        if answering.is_set():
            break


    # small silence tail to help VAD infer end-of-speech
    for i in range(5):
        await queue.put(silence_chunk())
    await queue.put(None) # None to denote the end of the prompt    
    
    await queue.join() # Waits for queue to empty

    return end

async def play_reply_streaming(session):
    """Receive ONE model turn and play audio as it arrives (plus print transcript + tool debug)."""
    stream_id = None
    while True:
        turn = session.receive()
        got_audio = False
        saw_tooling = False

        array = bytearray([])
        chunk_accum = 0

        async for resp in turn: 

            sc = getattr(resp, "server_content", None)
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
                        if not stream_id:
                            stream_id = int(time.time() * 1000)
                        got_audio = True
                        answering.set()
                        array.extend(bytes(inline.data))
                        chunk_accum += len(inline.data)

            if chunk_accum > 0:
                resampled = await asyncio.to_thread(array_resample, array, IN_RATE, OUT_RATE)
                await asyncio.to_thread(play_pcm_stream, audioClient, resampled, stream_id, chunk_size = CHUNK_SIZE, sleep_time = DT)
                chunk_accum = 0
                array = bytearray([])

            if got_audio and getattr(sc, "turn_complete", False):
                stream_id = None
                turn_complete.set()
                answering.clear()
                break
                
        if not got_audio:
            print("[WARN] No audio reply received.")
        if not saw_tooling:
            print("[INFO] No tool/code-execution observed this turn (likely answered without Search).")


async def send_one_turn(session):
    """
    Send one utterance to the *same* live session.
    We pace chunks roughly in real-time so VAD behaves more reliably.
    """
    while True:
        t0 = time.time()
        frame = await queue.get()
        
        if frame is None:
            queue.task_done()
            await session.send_realtime_input(audio_stream_end=True)
            continue
            
        chunk_secs = len(frame) / 2 / MIC_RATE
        #for ch in frames:
        try:
            await session.send_realtime_input(audio={"data": frame, "mime_type": f"audio/pcm;rate={MIC_RATE}"})
        except Exception as e:
            print(f"[SESSION ERROR]: {e}")
        queue.task_done()
        await asyncio.sleep(chunk_secs - (time.time() - t0))  # helps VAD / turn-taking consistency



async def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", MCAST_PORT))

    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton("192.168.123.164"))

    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setblocking(False)

    send_task = None
    play_task = None
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            end = True
            turn_complete.set()
            while True:
                if end:
                    await wait_for_wakeword(sock, WAKE_WORD)
                    end = False
                    if send_task is None:
                        send_task = asyncio.create_task(send_one_turn(session))
                        play_task = asyncio.create_task(play_reply_streaming(session))

                try:
                    await turn_complete.wait()
                except Exception as e:
                    print(f"Excepcion {e}")
                turn_complete.clear()
                end = await record_until_silence(sock, max_seconds = 30.0, end_word = END_WORD)
    finally:
        if send_task:
            send_task.cancel()
        if play_task:
            play_task.cancel()
        stop_pcm_stream(audioClient)
        print("Exiting...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
