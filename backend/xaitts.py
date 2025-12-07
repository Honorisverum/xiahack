"""
xAI Streaming TTS Plugin for LiveKit Agents

Uses WebSocket streaming API for low-latency text-to-speech.
API: wss://api.x.ai/v1/realtime/audio/speech
Audio format: PCM linear16, 24kHz, mono
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Literal

import websockets
from livekit.agents import tts, APIConnectOptions, APIConnectionError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

SAMPLE_RATE = 24000
NUM_CHANNELS = 1

XAI_VOICES = Literal["ara", "rex", "sal", "eve", "una", "leo"]


@dataclass
class _TTSOptions:
    voice: XAI_VOICES
    api_key: str
    base_url: str


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        voice: XAI_VOICES = "ara",
        api_key: str | None = None,
        base_url: str = "https://api.x.ai/v1",
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )

        api_key = api_key or os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY not found")

        self._opts = _TTSOptions(
            voice=voice,
            api_key=api_key,
            base_url=base_url,
        )

    @property
    def model(self) -> str:
        return "xai-streaming-tts"

    @property
    def provider(self) -> str:
        return "xai"

    def update_options(self, *, voice: XAI_VOICES | None = None) -> None:
        if voice:
            self._opts.voice = voice

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "ChunkedStream":
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        pass


class ChunkedStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: TTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        opts = self._tts._opts
        ws_url = opts.base_url.replace("https://", "wss://").replace("http://", "ws://")
        uri = f"{ws_url}/realtime/audio/speech"
        headers = {"Authorization": f"Bearer {opts.api_key}"}

        request_id = f"xai-tts-{id(self)}"

        try:
            async with websockets.connect(
                uri,
                additional_headers=headers,
                close_timeout=5,
            ) as ws:
                # Send config
                await ws.send(json.dumps({
                    "type": "config",
                    "data": {"voice_id": opts.voice}
                }))

                # Send text (all at once for non-streaming)
                await ws.send(json.dumps({
                    "type": "text_chunk",
                    "data": {"text": self.input_text, "is_last": True}
                }))

                output_emitter.initialize(
                    request_id=request_id,
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                )

                # Receive audio chunks
                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(response)

                        audio_b64 = data["data"]["data"]["audio"]
                        is_last = data["data"]["data"].get("is_last", False)

                        chunk_bytes = base64.b64decode(audio_b64)
                        if chunk_bytes:
                            output_emitter.push(chunk_bytes)

                        if is_last:
                            break

                    except asyncio.TimeoutError:
                        raise APIConnectionError("Timeout waiting for audio") from None

        except websockets.exceptions.WebSocketException as e:
            raise APIConnectionError(f"WebSocket error: {e}") from e
        except Exception as e:
            raise APIConnectionError(f"TTS error: {e}") from e

