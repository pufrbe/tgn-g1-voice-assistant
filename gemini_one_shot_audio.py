#!/usr/bin/env python3
import argparse
import asyncio
import time

import pyaudio
from google import genai

# Your exact devices
IN_DEV = 24    # ReSpeaker 4 Mic Array
OUT_DEV = 26   # pulse (routes to default BT headphones sink)

# Audio formats
FORMAT = pyaudio.paInt16
CHANNELS = 1
MIC_RATE = 16000          # your mic default, and Live input is natively 16kHz :contentReference[oaicite:1]{index=1}
OUT_RATE = 24000          # Live API audio output is always 24kHz :contentReference[oaicite:2]{index=2}
CHUNK = 1024

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": "You are a helpful voice assistant. Reply concisely.",
}

pya = pyaudio.PyAudio()
client = genai.Client()


def record_pcm(seconds: float, in_dev: int) -> list[bytes]:
    """Record raw 16-bit PCM mono from microphone."""
    stream = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=MIC_RATE,
        input=True,
        input_device_index=in_dev,
        frames_per_buffer=CHUNK,
    )
    frames = []
    try:
        n_frames = int((MIC_RATE / CHUNK) * seconds)
        for _ in range(n_frames):
            frames.append(stream.read(CHUNK, exception_on_overflow=False))
    finally:
        stream.stop_stream()
        stream.close()
    return frames


async def main():
    ap = argparse.ArgumentParser(description="One-shot mic -> Gemini Live -> speaker")
    ap.add_argument("--seconds", type=float, default=6.0, help="Record duration")
    ap.add_argument("--in-dev", type=int, default=IN_DEV, help="Input device index")
    ap.add_argument("--out-dev", type=int, default=OUT_DEV, help="Output device index")
    args = ap.parse_args()

    print(f"Mic device: {args.in_dev} @ {MIC_RATE}Hz | Output device: {args.out_dev} @ {OUT_RATE}Hz")
    input("Press ENTER to record... (use headphones)\n")

    frames = record_pcm(args.seconds, args.in_dev)
    print(f"Recorded {args.seconds:.2f}s. Sending to Gemini...")

    # Speaker stream (24kHz PCM from Live API) :contentReference[oaicite:3]{index=3}
    out_stream = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUT_RATE,
        output=True,
        output_device_index=args.out_dev,
        frames_per_buffer=CHUNK,
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
            # Send all recorded audio chunks (tell Live the input rate via MIME type) :contentReference[oaicite:4]{index=4}
            for chunk in frames:
                await session.send_realtime_input(
                    audio={"data": chunk, "mime_type": f"audio/pcm;rate={MIC_RATE}"}
                )

            # Small silence tail helps end-of-utterance detection
            silence = b"\x00\x00" * CHUNK
            for _ in range(5):  # ~320ms
                await session.send_realtime_input(
                    audio={"data": silence, "mime_type": f"audio/pcm;rate={MIC_RATE}"}
                )

            print("Waiting for audio reply...")

            # Receive until the turn completes; play audio as it arrives
            got_any_audio = False
            t0 = time.time()
            timeout_s = 20

            async for resp in session.receive():
                sc = getattr(resp, "server_content", None)
                if sc and getattr(sc, "model_turn", None):
                    for part in sc.model_turn.parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and isinstance(inline.data, (bytes, bytearray)):
                            got_any_audio = True
                            await asyncio.to_thread(out_stream.write, bytes(inline.data))

                if sc and getattr(sc, "turn_complete", False):
                    break

                if time.time() - t0 > timeout_s:
                    print("Timed out waiting for a reply.")
                    break

            if not got_any_audio:
                print("No audio returned (check model/config/key).")
            else:
                print("Done.")
    finally:
        out_stream.stop_stream()
        out_stream.close()
        pya.terminate()


if __name__ == "__main__":
    asyncio.run(main())
