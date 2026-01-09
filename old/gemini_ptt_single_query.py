#!/usr/bin/env python3
import asyncio
import time
import threading

import pyaudio
from pynput import keyboard
from google import genai

# ---- Your known-good devices ----
IN_DEV = 24     # ReSpeaker 4 Mic Array
OUT_DEV = 26    # pulse (routes to default BT sink)

# ---- Audio params ----
FORMAT = pyaudio.paInt16
CHANNELS = 1
MIC_RATE = 16000
OUT_RATE = 24000          # Gemini Live audio output rate
CHUNK = 1024              # ~64ms at 16kHz

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": "You are a helpful voice assistant. Reply concisely.",
}

pya = pyaudio.PyAudio()
client = genai.Client()


class PTT:
    def __init__(self):
        self.pressed = False
        self.started = threading.Event()
        self.released = threading.Event()

    def on_press(self, key):
        if key == keyboard.Key.space and not self.pressed:
            self.pressed = True
            self.started.set()
            print("[PTT] recording... (release SPACE to send)")

    def on_release(self, key):
        if key == keyboard.Key.space and self.pressed:
            self.pressed = False
            self.released.set()
            print("[PTT] released. Sending to Gemini...")


def record_until_release(ptt: PTT, max_seconds: float = 30.0) -> list[bytes]:
    """Record PCM frames while SPACE is held (up to max_seconds)."""
    stream = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=MIC_RATE,
        input=True,
        input_device_index=IN_DEV,
        frames_per_buffer=CHUNK,
    )

    frames: list[bytes] = []
    t0 = time.time()
    try:
        while not ptt.released.is_set():
            if time.time() - t0 > max_seconds:
                print("[PTT] max record time reached, stopping.")
                break
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
    finally:
        stream.stop_stream()
        stream.close()

    return frames


async def play_one_reply(session):
    """Receive one model turn and play audio as it arrives."""
    out_stream = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUT_RATE,
        output=True,
        output_device_index=OUT_DEV,
        frames_per_buffer=CHUNK,
    )
    got_audio = False
    try:
        t0 = time.time()
        timeout_s = 25

        async for resp in session.receive():
            sc = getattr(resp, "server_content", None)
            if sc and getattr(sc, "model_turn", None):
                for part in sc.model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and isinstance(inline.data, (bytes, bytearray)):
                        got_audio = True
                        await asyncio.to_thread(out_stream.write, bytes(inline.data))

            if sc and getattr(sc, "turn_complete", False):
                break

            if time.time() - t0 > timeout_s:
                print("Timed out waiting for model audio.")
                break

        return got_audio
    finally:
        out_stream.stop_stream()
        out_stream.close()


async def main():
    print(f"Mic: device {IN_DEV} @ {MIC_RATE}Hz | Output: device {OUT_DEV} (pulse) @ {OUT_RATE}Hz")
    print("Hold SPACE to talk. Release SPACE to send. Ctrl+C to quit.\n")

    ptt = PTT()
    listener = keyboard.Listener(on_press=ptt.on_press, on_release=ptt.on_release)
    listener.start()

    try:
        # Wait for SPACE press
        while not ptt.started.is_set():
            await asyncio.sleep(0.02)

        # Record in a thread so key listener remains responsive
        frames = await asyncio.to_thread(record_until_release, ptt)

        if not frames:
            print("No audio captured.")
            return

        # Open a live session, send audio once, then play the one reply.
        async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
            for chunk in frames:
                await session.send_realtime_input(
                    audio={"data": chunk, "mime_type": f"audio/pcm;rate={MIC_RATE}"}
                )

            # Short silence tail helps end-of-utterance detection
            silence = b"\x00\x00" * CHUNK
            for _ in range(5):
                await session.send_realtime_input(
                    audio={"data": silence, "mime_type": f"audio/pcm;rate={MIC_RATE}"}
                )

            print("[Gemini] replying...")
            got_audio = await play_one_reply(session)

        if not got_audio:
            print("No audio returned (check model name/key/config).")
        else:
            print("Done. Exiting.")
    finally:
        listener.stop()
        pya.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
