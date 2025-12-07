"""
xAI Voice Cloning TTS Plugin for LiveKit Agents

Uses REST API with voice cloning support.
API: https://us-east-4.api.x.ai/voice-staging/api/v1/text-to-speech/generate
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests
from livekit.agents import tts, APIConnectOptions, APIConnectionError
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

logger = logging.getLogger("root")

SAMPLE_RATE = 24000
NUM_CHANNELS = 1

# Voice files mapping (relative to project root)
VOICE_CLONE_FILES = {
    "romaco": "myvoices/romaco.mp3",
    "yuri": "myvoices/yuri.mp3",
    "mina": "myvoices/mina.mp3",
}

CLONE_API_URL = "https://us-east-4.api.x.ai/voice-staging/api/v1/text-to-speech/generate"


@lru_cache(maxsize=8)
def _file_to_base64(file_path: str) -> str:
    """Cache voice file base64 to avoid repeated disk reads."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked generation."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


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

        # Cache voice base64 once
        voice_b64 = None
        if opts.voice_file and os.path.exists(opts.voice_file):
            b64_start = time.perf_counter()
            voice_b64 = _file_to_base64(opts.voice_file)
            b64_time = time.perf_counter() - b64_start
            if b64_time > 0.01:  # Only log if > 10ms (not cached)
                logger.info(f"[TTS] Base64 encoding: {b64_time:.3f}s (file: {opts.voice_file})")

        headers = {"Authorization": f"Bearer {opts.api_key}"}

        # Split into sentences for lower perceived latency
        sentences = _split_sentences(self.input_text)
        if not sentences:
            sentences = [self.input_text]

        logger.info(f"[TTS] Chunked into {len(sentences)} sentences: {sentences}")
        total_start = time.perf_counter()
        initialized = False

        for i, sentence in enumerate(sentences):
            payload = {
                "model": "grok-voice",
                "input": sentence,
                "response_format": "mp3",
                "instructions": "audio",
                "voice": voice_b64 or "None",
                "sampling_params": {
                    "max_new_tokens": 1024,
                    "temperature": 1.0,
                    "min_p": 0.01,
                },
            }

            try:
                chunk_start = time.perf_counter()
                response = requests.post(
                    CLONE_API_URL,
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=30,
                )
                response.raise_for_status()
                api_time = time.perf_counter() - chunk_start

                mp3_bytes = b"".join(response.iter_content(chunk_size=8192))
                
                ffmpeg_start = time.perf_counter()
                pcm_bytes = _mp3_to_pcm(mp3_bytes)
                ffmpeg_time = time.perf_counter() - ffmpeg_start

                logger.info(
                    f"[TTS] Chunk {i+1}/{len(sentences)}: "
                    f"'{sentence[:30]}...' | API: {api_time:.2f}s | ffmpeg: {ffmpeg_time:.3f}s | "
                    f"audio: {len(pcm_bytes)//2//SAMPLE_RATE:.1f}s"
                )

                if not initialized:
                    output_emitter.initialize(
                        request_id=request_id,
                        sample_rate=SAMPLE_RATE,
                        num_channels=NUM_CHANNELS,
                        mime_type="audio/pcm",
                    )
                    initialized = True
                    logger.info(f"[TTS] First chunk ready in {time.perf_counter() - total_start:.2f}s")

                output_emitter.push(pcm_bytes)

            except requests.RequestException as e:
                raise APIConnectionError(f"Voice clone API error: {e}") from e
            except Exception as e:
                raise APIConnectionError(f"TTS error: {e}") from e

