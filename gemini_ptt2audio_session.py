#!/usr/bin/env python3
import asyncio
import time
from dataclasses import dataclass

import pyaudio
from pynput import keyboard
from google import genai

# ---- Your known-good devices ----
IN_DEV = 24     # ReSpeaker 4 Mic Array
OUT_DEV = 26    # pulse (routes to default BT sink)

# ---- Audio ----
FORMAT = pyaudio.paInt16
CHANNELS = 1
MIC_RATE = 16000
OUT_RATE = 24000
CHUNK = 1024  # ~64ms

# ---- Gemini ----
MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": "You are a helpful voice assistant. Reply concisely.",
}

pya = pyaudio.PyAudio()
client = genai.Client()


@dataclass
class PTTState:
    pressed: bool = False
    press_t: float = 0.0
    last_event_t: float = 0.0


stop_event = asyncio.Event()
utterance_q: asyncio.Queue[list[bytes]] = asyncio.Queue(maxsize=4)
ptt = PTTState()


def start_ptt_listener(loop: asyncio.AbstractEventLoop):
    """
    SPACE hold records; release queues one utterance.
    Debounce prevents spurious press/release oscillations from triggering queries.
    """
    DEBOUNCE_S = 0.08         # ignore events closer than this
    MIN_HOLD_S = 0.12         # must hold at least this long to accept a release

    def on_press(key):
        if key == keyboard.Key.esc:
            loop.call_soon_threadsafe(stop_event.set)
            return False

        if key != keyboard.Key.space:
            return

        now = time.monotonic()
        if now - ptt.last_event_t < DEBOUNCE_S:
            return
        ptt.last_event_t = now

        if not ptt.pressed:
            ptt.pressed = True
            ptt.press_t = now
            print("[PTT] talking... (release SPACE to send)")

    def on_release(key):
        if key != keyboard.Key.space:
            return

        now = time.monotonic()
        if now - ptt.last_event_t < DEBOUNCE_S:
            return
        ptt.last_event_t = now

        if ptt.pressed:
            held = now - ptt.press_t
            ptt.pressed = False

            # Ignore tiny “ghost” taps
            if held < MIN_HOLD_S:
                # don’t print released for noise
                return

            print("[PTT] released. Sending...")

            # signal recorder to stop and queue what it captured
            loop.call_soon_threadsafe(_stop_recording_flag.set)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    return listener


# A thread-safe-ish flag we flip from the key listener to stop the current recording.
_stop_recording_flag = asyncio.Event()


async def record_utterances():
    """
    Wait for SPACE press, record mic frames until release, then put frames into utterance_q.
    No Gemini traffic happens here.
    """
    stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=MIC_RATE,
        input=True,
        input_device_index=IN_DEV,
        frames_per_buffer=CHUNK,
    )

    try:
        while not stop_event.is_set():
            # Wait for a press
            while not ptt.pressed and not stop_event.is_set():
                await asyncio.sleep(0.01)
            if stop_event.is_set():
                break

            _stop_recording_flag.clear()
            frames: list[bytes] = []

            # Record until release triggers the flag
            while ptt.pressed and not _stop_recording_flag.is_set() and not stop_event.is_set():
                data = await asyncio.to_thread(stream.read, CHUNK, exception_on_overflow=False)
                frames.append(data)

            # If we got something meaningful, queue it
            if frames and not stop_event.is_set():
                # Small silence tail helps end-of-utterance
                silence = b"\x00\x00" * CHUNK
                frames.extend([silence] * 5)
                try:
                    utterance_q.put_nowait(frames)
                except asyncio.QueueFull:
                    print("[WARN] utterance queue full; dropping.")
    finally:
        stream.close()


async def play_reply_audio(pcm_chunks: list[bytes]):
    out_stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=OUT_RATE,
        output=True,
        output_device_index=OUT_DEV,
        frames_per_buffer=CHUNK,
    )
    try:
        for ch in pcm_chunks:
            await asyncio.to_thread(out_stream.write, ch)
    finally:
        out_stream.stop_stream()
        out_stream.close()


async def send_one_utterance(frames: list[bytes]):
    """
    One complete billable interaction:
    - open session
    - send buffered audio
    - receive one audio turn
    - play it
    - close session
    """
    reply_chunks: list[bytes] = []

    async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
        for ch in frames:
            await session.send_realtime_input(audio={"data": ch, "mime_type": f"audio/pcm;rate={MIC_RATE}"})

        # Receive until turn_complete
        async for resp in session.receive():
            sc = getattr(resp, "server_content", None)
            if sc and getattr(sc, "model_turn", None):
                for part in sc.model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and isinstance(inline.data, (bytes, bytearray)):
                        reply_chunks.append(bytes(inline.data))
            if sc and getattr(sc, "turn_complete", False):
                break

    if reply_chunks:
        await play_reply_audio(reply_chunks)
    else:
        print("[WARN] No audio reply received.")


async def main():
    loop = asyncio.get_running_loop()
    _listener = start_ptt_listener(loop)

    print(f"Mic device {IN_DEV} @ {MIC_RATE} Hz")
    print(f"Output device {OUT_DEV} (pulse) @ {OUT_RATE} Hz")
    print("Hold SPACE to talk. Release to send. ESC to quit.\n")

    recorder = asyncio.create_task(record_utterances())

    try:
        while not stop_event.is_set():
            frames = await utterance_q.get()
            if stop_event.is_set():
                break
            await send_one_utterance(frames)
    finally:
        stop_event.set()
        recorder.cancel()
        await asyncio.gather(recorder, return_exceptions=True)
        try:
            _listener.stop()
        except Exception:
            pass
        pya.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
