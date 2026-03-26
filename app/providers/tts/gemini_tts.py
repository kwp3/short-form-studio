from typing import List, Optional, Union

from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.providers import register_tts
from app.providers.base import TTSProvider


def get_gemini_voices() -> list[str]:
    voices_with_gender = [
        ("Zephyr", "Female"),
        ("Puck", "Male"),
        ("Charon", "Male"),
        ("Kore", "Female"),
        ("Fenrir", "Male"),
        ("Aoede", "Female"),
        ("Thalia", "Female"),
        ("Sage", "Male"),
        ("Echo", "Female"),
        ("Harmony", "Female"),
        ("Lux", "Female"),
        ("Nova", "Female"),
        ("Vale", "Male"),
        ("Orion", "Male"),
        ("Atlas", "Male"),
    ]
    return [
        f"gemini:{voice}-{gender}"
        for voice, gender in voices_with_gender
    ]


@register_tts
class GeminiTTSProvider(TTSProvider):
    @staticmethod
    def provider_name() -> str:
        return "gemini"

    def get_voices(self) -> List[str]:
        return get_gemini_voices()

    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        # Parse voice_name: "gemini:Zephyr-Female" -> "Zephyr"
        parts = voice_name.split(":")
        if len(parts) < 2:
            logger.error(f"Invalid gemini voice name format: {voice_name}")
            return None

        voice_with_gender = parts[1]
        voice = voice_with_gender.split("-")[0]

        import base64
        import io
        from pydub import AudioSegment
        import google.generativeai as genai

        try:
            api_key = config.app.get("gemini_api_key", "")
            if not api_key:
                logger.error("Gemini API key is not set")
                return None

            genai.configure(api_key=api_key)

            logger.info(f"start, voice name: {voice}, try: 1")

            model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")

            generation_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": voice
                        }
                    }
                }
            }

            response = model.generate_content(
                contents=text,
                generation_config=generation_config
            )

            if not response.candidates or not response.candidates[0].content:
                logger.error("No audio content received from Gemini TTS")
                return None

            audio_data = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    audio_data = part.inline_data.data
                    break

            if not audio_data:
                logger.error("No audio data found in response")
                return None

            if isinstance(audio_data, str):
                audio_bytes = base64.b64decode(audio_data)
            else:
                audio_bytes = audio_data

            try:
                audio_segment = AudioSegment.from_file(
                    io.BytesIO(audio_bytes),
                    format="raw",
                    frame_rate=24000,
                    channels=1,
                    sample_width=2
                )
            except Exception as e:
                logger.error(f"Failed to load PCM audio: {e}")
                return None

            audio_segment.export(voice_file, format="mp3")

            logger.info(f"completed, output file: {voice_file}")

            sub_maker = SubMaker()
            audio_duration = len(audio_segment) / 1000.0
            audio_duration_100ns = int(audio_duration * 10000000)

            sub_maker.subs = [text]
            sub_maker.offset = [(0, audio_duration_100ns)]

            return sub_maker

        except ImportError as e:
            logger.error(f"Missing required package for Gemini TTS: {str(e)}. Please install: pip install pydub")
            return None
        except Exception as e:
            logger.error(f"Gemini TTS failed, error: {str(e)}")
            return None
