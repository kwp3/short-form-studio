from typing import List, Optional, Union

import requests
from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.providers import register_tts
from app.providers.base import TTSProvider
from app.utils import utils


def get_siliconflow_voices() -> list[str]:
    voices_with_gender = [
        ("FunAudioLLM/CosyVoice2-0.5B", "alex", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "anna", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "bella", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "benjamin", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "charles", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "claire", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "david", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "diana", "Female"),
    ]
    return [
        f"siliconflow:{model}:{voice}-{gender}"
        for model, voice, gender in voices_with_gender
    ]


@register_tts
class SiliconFlowProvider(TTSProvider):
    @staticmethod
    def provider_name() -> str:
        return "siliconflow"

    def get_voices(self) -> List[str]:
        return get_siliconflow_voices()

    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        # Parse voice_name: "siliconflow:model:voice-Gender"
        parts = voice_name.split(":")
        if len(parts) < 3:
            logger.error(f"Invalid siliconflow voice name format: {voice_name}")
            return None

        model = parts[1]
        voice_with_gender = parts[2]
        voice = voice_with_gender.split("-")[0]
        full_voice = f"{model}:{voice}"

        text = text.strip()
        api_key = config.siliconflow.get("api_key", "")

        if not api_key:
            logger.error("SiliconFlow API key is not set")
            return None

        # Convert voice_volume to SiliconFlow gain range
        gain = voice_volume - 1.0
        gain = max(-10, min(10, gain))

        url = "https://api.siliconflow.cn/v1/audio/speech"

        payload = {
            "model": model,
            "input": text,
            "voice": full_voice,
            "response_format": "mp3",
            "sample_rate": 32000,
            "stream": False,
            "speed": voice_rate,
            "gain": gain,
        }

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        for i in range(3):
            try:
                logger.info(
                    f"start siliconflow tts, model: {model}, voice: {full_voice}, try: {i + 1}"
                )

                response = requests.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    with open(voice_file, "wb") as f:
                        f.write(response.content)

                    sub_maker = SubMaker()

                    try:
                        from moviepy import AudioFileClip

                        audio_clip = AudioFileClip(voice_file)
                        audio_duration = audio_clip.duration
                        audio_clip.close()

                        audio_duration_100ns = int(audio_duration * 10000000)

                        sentences = utils.split_string_by_punctuations(text)

                        if sentences:
                            total_chars = sum(len(s) for s in sentences)
                            char_duration = (
                                audio_duration_100ns / total_chars if total_chars > 0 else 0
                            )

                            current_offset = 0
                            for sentence in sentences:
                                if not sentence.strip():
                                    continue
                                sentence_chars = len(sentence)
                                sentence_duration = int(sentence_chars * char_duration)
                                sub_maker.subs.append(sentence)
                                sub_maker.offset.append(
                                    (current_offset, current_offset + sentence_duration)
                                )
                                current_offset += sentence_duration
                        else:
                            sub_maker.subs = [text]
                            sub_maker.offset = [(0, audio_duration_100ns)]

                    except Exception as e:
                        logger.warning(f"Failed to create accurate subtitles: {str(e)}")
                        sub_maker.subs = [text]
                        sub_maker.offset = [
                            (
                                0,
                                audio_duration_100ns
                                if "audio_duration_100ns" in locals()
                                else 10000000,
                            )
                        ]

                    logger.success(f"siliconflow tts succeeded: {voice_file}")
                    return sub_maker
                else:
                    logger.error(
                        f"siliconflow tts failed with status code {response.status_code}: {response.text}"
                    )
            except Exception as e:
                logger.error(f"siliconflow tts failed: {str(e)}")

        return None
