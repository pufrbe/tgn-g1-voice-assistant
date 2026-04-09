#!/bin/env python3
import math

import numpy as np
from scipy import signal

from google import genai
from google.genai import types

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

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

def array_resample(array : bytearray, in_rate : int, out_rate : int):
    factor = math.gcd(in_rate, out_rate)
    up = out_rate//factor
    down = in_rate//factor
    x = np.frombuffer(array, dtype=np.int16).astype(np.float32)
    y = signal.resample_poly(x, up, down)

    data = np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    return data

def main():
    print("[INFO] Initializing audio client...")
    net_if = "eth0"
    ChannelFactoryInitialize(0, net_if)
    audio_client = AudioClient()
    audio_client.SetTimeout(10.0)
    audio_client.Init()
    print("[INFO] Audio client initialized.")

    client = genai.Client()

    try:
        print("[INFO] Sending request to Gemini API...")
        response = client.models.generate_content(
           model="gemini-2.5-flash-preview-tts",
           #model="gemini-2.5-flash-lite-preview-tts",
           contents="Di lo siguiente animadamente y con acento argentino: Hola y bienvenidos a todos! Estamos aca presentando el proyecto de robotizacion de tareas de TGN.",
           config=types.GenerateContentConfig(
              response_modalities=["AUDIO"],
              speech_config=types.SpeechConfig(
                 voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                       voice_name='Puck',
                    )
                 )
              ),
           )
        )
        print("[INFO] Response received from Gemini API.")
        data = response.candidates[0].content.parts[0].inline_data.data
        data = array_resample(data, 24000, 16000)
        print("[INFO] Playing audio...")
        play_pcm_stream(audio_client, data, 134234)
        print("[INFO] Exiting...")
    except Exception as e:
        print(f"\nException: {e}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
