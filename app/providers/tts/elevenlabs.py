import base64
from typing import List, Optional

import requests
from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.providers import register_tts
from app.providers.base import TTSProvider
from app.utils import utils


# Popular default voices available on all ElevenLabs accounts (including free tier)
_DEFAULT_VOICES = [
    ("21m00Tcm4TlvDq8ikWAM", "Rachel", "Female"),
    ("AZnzlk1XvdvUeBnXmlld", "Domi", "Female"),
    ("EXAVITQu4vr4xnSDxMaL", "Bella", "Female"),
    ("ErXwobaYiN019PkySvjV", "Antoni", "Male"),
    ("MF3mGyEYCl7XYWbV9V6O", "Elli", "Female"),
    ("TxGEqnHWrfWFTfGW9XjX", "Josh", "Male"),
    ("VR6AewLTigWG4xSOukaG", "Arnold", "Male"),
    ("pNInz6obpgDQGcFmaJgB", "Adam", "Male"),
    ("yoZ06aMxZJJ28mfd3POQ", "Sam", "Male"),
    ("jBpfuIE2acCO8z3wKNLl", "Gigi", "Female"),
    ("onwK4e9ZLuTAKqWW03F9", "Daniel", "Male"),
    ("XB0fDUnXU5powFXDhCwa", "Charlotte", "Female"),
]


def get_elevenlabs_voices() -> list[str]:
    return [
        f"elevenlabs:{voice_id}-{name}-{gender}"
        for voice_id, name, gender in _DEFAULT_VOICES
    ]


def _chars_to_words(characters, start_times, end_times):
    """Group character-level alignment into word-level SubMaker entries.

    Returns (words, offsets) where offsets are (start, end) tuples in 100ns ticks.
    """
    words = []
    offsets = []
    current_word = ""
    word_start = None
    word_end = None

    for char, start, end in zip(characters, start_times, end_times):
        if char in (" ", "\n", "\r", "\t"):
            if current_word:
                words.append(current_word)
                offsets.append((int(word_start * 1e7), int(word_end * 1e7)))
                current_word = ""
                word_start = None
        else:
            if word_start is None:
                word_start = start
            word_end = end
            current_word += char

    # Flush last word
    if current_word and word_start is not None:
        words.append(current_word)
        offsets.append((int(word_start * 1e7), int(word_end * 1e7)))

    return words, offsets


def _estimate_subtitles(text, voice_file):
    """Fallback: proportional timing estimation (same approach as SiliconFlow)."""
    sub_maker = SubMaker()
    try:
        from moviepy import AudioFileClip

        audio_clip = AudioFileClip(voice_file)
        audio_duration = audio_clip.duration
        audio_clip.close()

        audio_duration_100ns = int(audio_duration * 1e7)
        sentences = utils.split_string_by_punctuations(text)

        if sentences:
            total_chars = sum(len(s) for s in sentences)
            char_duration = audio_duration_100ns / total_chars if total_chars > 0 else 0
            current_offset = 0
            for sentence in sentences:
                if not sentence.strip():
                    continue
                sentence_duration = int(len(sentence) * char_duration)
                sub_maker.subs.append(sentence)
                sub_maker.offset.append((current_offset, current_offset + sentence_duration))
                current_offset += sentence_duration
        else:
            sub_maker.subs = [text]
            sub_maker.offset = [(0, audio_duration_100ns)]
    except Exception as e:
        logger.warning(f"Failed to estimate subtitles: {e}")
        sub_maker.subs = [text]
        sub_maker.offset = [(0, 10_000_000)]

    return sub_maker


@register_tts
class ElevenLabsProvider(TTSProvider):
    @staticmethod
    def provider_name() -> str:
        return "elevenlabs"

    def get_voices(self) -> List[str]:
        return get_elevenlabs_voices()

    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        # Parse voice_name: "elevenlabs:{voice_id}-{Name}-{Gender}"
        parts = voice_name.split(":")
        if len(parts) < 2:
            logger.error(f"Invalid elevenlabs voice name format: {voice_name}")
            return None

        # voice_id is the segment before the first hyphen in the second part
        voice_segment = parts[1]
        voice_id = voice_segment.split("-")[0]

        text = text.strip()
        api_key = config.elevenlabs.get("api_key", "")

        if not api_key:
            logger.error("ElevenLabs API key is not set")
            return None

        if voice_rate != 1.0:
            logger.warning(
                f"ElevenLabs does not support voice_rate adjustment (got {voice_rate}), using default speed"
            )

        model_id = config.elevenlabs.get("model_id", "eleven_multilingual_v2")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        for i in range(3):
            try:
                logger.info(f"start elevenlabs tts, voice_id: {voice_id}, model: {model_id}, try: {i + 1}")

                response = requests.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()

                    # Decode audio and write to file
                    audio_bytes = base64.b64decode(data["audio_base64"])
                    with open(voice_file, "wb") as f:
                        f.write(audio_bytes)

                    # Build subtitles from alignment data
                    alignment = data.get("alignment")
                    if alignment and alignment.get("characters"):
                        words, offsets = _chars_to_words(
                            alignment["characters"],
                            alignment["character_start_times_seconds"],
                            alignment["character_end_times_seconds"],
                        )

                        sub_maker = SubMaker()
                        sub_maker.subs = words
                        sub_maker.offset = offsets
                    else:
                        logger.warning("No alignment data from ElevenLabs, using estimated timing")
                        sub_maker = _estimate_subtitles(text, voice_file)

                    logger.success(f"elevenlabs tts succeeded: {voice_file}")
                    return sub_maker
                else:
                    logger.error(
                        f"elevenlabs tts failed with status {response.status_code}: {response.text}"
                    )
                    # Don't retry on auth/billing errors
                    if response.status_code in (401, 402, 403):
                        break
            except Exception as e:
                logger.error(f"elevenlabs tts failed: {e}")

        return None
