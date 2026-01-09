#!/usr/bin/env python3
import argparse
import sys
import time
import pyaudio

FORMAT = pyaudio.paInt16
CHANNELS = 1

def list_devices(p: pyaudio.PyAudio):
    print("\n=== Audio Devices ===")
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        name = info.get("name", "")
        host = p.get_host_api_info_by_index(info["hostApi"]).get("name", "")
        max_in = int(info.get("maxInputChannels", 0))
        max_out = int(info.get("maxOutputChannels", 0))
        default_sr = info.get("defaultSampleRate", 0)
        print(f"[{i:2d}] {name} | host={host} | in={max_in} out={max_out} | default_sr={default_sr}")

    try:
        din = p.get_default_input_device_info()
        dout = p.get_default_output_device_info()
        print("\nDefault input :", f'[{din["index"]}] {din["name"]}')
        print("Default output:", f'[{dout["index"]}] {dout["name"]}')
    except Exception as e:
        print("\nCould not read default devices:", e)

def open_streams(p: pyaudio.PyAudio, rate: int, chunk: int, in_dev: int, out_dev: int):
    in_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=rate,
        input=True,
        input_device_index=in_dev,
        frames_per_buffer=chunk,
    )
    out_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=rate,
        output=True,
        output_device_index=out_dev,
        frames_per_buffer=chunk,
    )
    return in_stream, out_stream

def main():
    ap = argparse.ArgumentParser(description="Mic loopback test: mic -> speaker")
    ap.add_argument("--rate", type=int, default=16000, help="Sample rate (try 16000 or 48000)")
    ap.add_argument("--chunk", type=int, default=1024, help="Frames per buffer")
    ap.add_argument("--seconds", type=int, default=10, help="How long to run")
    ap.add_argument("--in-dev", type=int, default=None, help="Input device index (see --list)")
    ap.add_argument("--out-dev", type=int, default=None, help="Output device index (see --list)")
    ap.add_argument("--list", action="store_true", help="List devices and exit")
    args = ap.parse_args()

    p = pyaudio.PyAudio()
    try:
        if args.list:
            list_devices(p)
            return 0

        print("Starting mic loopback test...")
        print("Tips: use headphones to avoid feedback; speak normally.")
        print(f"rate={args.rate}, chunk={args.chunk}, seconds={args.seconds}")
        if args.in_dev is not None:
            print(f"Using input device index: {args.in_dev}")
        if args.out_dev is not None:
            print(f"Using output device index: {args.out_dev}")

        try:
            in_stream, out_stream = open_streams(p, args.rate, args.chunk, args.in_dev, args.out_dev)
        except Exception as e:
            print("\nFailed to open streams with these settings:", e)
            print("Try a different --rate (common: 48000) or pick devices with --in-dev/--out-dev after running --list.")
            return 2

        t_end = time.time() + args.seconds
        try:
            while time.time() < t_end:
                data = in_stream.read(args.chunk, exception_on_overflow=False)
                out_stream.write(data)
        except KeyboardInterrupt:
            pass
        finally:
            in_stream.stop_stream(); in_stream.close()
            out_stream.stop_stream(); out_stream.close()

        print("Done.")
        return 0
    finally:
        p.terminate()

if __name__ == "__main__":
    raise SystemExit(main())
