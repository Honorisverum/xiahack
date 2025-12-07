"""
xAI Voice Cloning TTS Plugin for LiveKit Agents

Uses REST API with voice cloning support.
API: https://us-east-4.api.x.ai/voice-staging/api/v1/text-to-speech/generate
"""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests
from livekit.agents import tts, APIConnectOptions, APIConnectionError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

SAMPLE_RATE = 24000
NUM_CHANNELS = 1

# Voice files mapping (relative to project root)
VOICE_CLONE_FILES = {
    "romaco": "myvoices/romaco.mp3",
    "yuri": "myvoices/yuri.mp3",
    "mina": "myvoices/mina.mp3",
}

CLONE_API_URL = "https://us-east-4.api.x.ai/voice-staging/api/v1/text-to-speech/generate"


def _file_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _mp3_to_pcm(mp3_bytes: bytes) -> bytes:
    """Convert mp3 to PCM linear16, 24kHz, mono using ffmpeg."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(NUM_CHANNELS),
            "pipe:1"
        ],
        input=mp3_bytes,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {proc.stderr.decode()}")
    return proc.stdout


@dataclass
class _TTSOptions:
    voice: str
    voice_file: str | None
    api_key: str


class VoiceCloneTTS(tts.TTS):
    """TTS with voice cloning via REST API."""

    def __init__(
        self,
        *,
        voice: str = "romaco",
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )

        api_key = api_key or os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY not found")

        voice_file = VOICE_CLONE_FILES.get(voice.lower())
        if voice_file:
            # Resolve relative to project root (one level up from backend/)
            project_root = Path(__file__).parent.parent
            voice_file = str(project_root / voice_file)

        self._opts = _TTSOptions(
            voice=voice.lower(),
            voice_file=voice_file,
            api_key=api_key,
        )

    @property
    def model(self) -> str:
        return "grok-voice-clone"

    @property
    def provider(self) -> str:
        return "xai"

    def update_options(self, *, voice: str | None = None) -> None:
        if voice:
            self._opts.voice = voice.lower()
            voice_file = VOICE_CLONE_FILES.get(voice.lower())
            if voice_file:
                project_root = Path(__file__).parent.parent
                self._opts.voice_file = str(project_root / voice_file)

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "VoiceCloneStream":
        return VoiceCloneStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        pass


class VoiceCloneStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: VoiceCloneTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: VoiceCloneTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        opts = self._tts._opts
        request_id = f"xai-clone-{id(self)}"

        # Build payload
        voice_b64 = None
        if opts.voice_file and os.path.exists(opts.voice_file):
            voice_b64 = _file_to_base64(opts.voice_file)

        payload = {
            "model": "grok-voice",
            "input": self.input_text,
            "response_format": "mp3",
            "instructions": "audio",
            "voice": voice_b64 or "None",
            "sampling_params": {
                "max_new_tokens": 512,
                "temperature": 1.0,
                "min_p": 0.01,
            },
        }

        headers = {"Authorization": f"Bearer {opts.api_key}"}

        try:
            response = requests.post(
                CLONE_API_URL,
                json=payload,
                headers=headers,
                stream=True,
                timeout=30,
            )
            response.raise_for_status()

            # Collect mp3 bytes
            mp3_bytes = b"".join(response.iter_content(chunk_size=8192))

            # Convert to PCM
            pcm_bytes = _mp3_to_pcm(mp3_bytes)

            output_emitter.initialize(
                request_id=request_id,
                sample_rate=SAMPLE_RATE,
                num_channels=NUM_CHANNELS,
                mime_type="audio/pcm",
            )
            output_emitter.push(pcm_bytes)

        except requests.RequestException as e:
            raise APIConnectionError(f"Voice clone API error: {e}") from e
        except Exception as e:
            raise APIConnectionError(f"TTS error: {e}") from e

