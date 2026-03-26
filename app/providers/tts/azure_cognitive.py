from datetime import datetime
from typing import List, Optional, Union

from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.providers import register_tts
from app.providers.base import TTSProvider


def _format_duration_to_offset(duration) -> int:
    if isinstance(duration, str):
        time_obj = datetime.strptime(duration, "%H:%M:%S.%f")
        milliseconds = (
            (time_obj.hour * 3600000)
            + (time_obj.minute * 60000)
            + (time_obj.second * 1000)
            + (time_obj.microsecond // 1000)
        )
        return milliseconds * 10000

    if isinstance(duration, int):
        return duration

    return 0


@register_tts
class AzureCognitiveProvider(TTSProvider):
    @staticmethod
    def provider_name() -> str:
        return "azure_cognitive"

    def get_voices(self) -> List[str]:
        # Azure Cognitive voices are the -V2 entries in the edge voice list
        from app.providers.tts.edge_tts_provider import get_all_azure_voices
        return [v for v in get_all_azure_voices() if "-V2" in v]

    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        # Parse voice name: strip gender suffix and -V2 suffix to get the actual Azure voice name
        voice_name = voice_name.replace("-Female", "").replace("-Male", "").strip()
        if voice_name.endswith("-V2"):
            voice_name = voice_name.replace("-V2", "").strip()

        if not voice_name:
            logger.error(f"invalid voice name: {voice_name}")
            raise ValueError(f"invalid voice name: {voice_name}")

        text = text.strip()

        for i in range(3):
            try:
                logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

                import azure.cognitiveservices.speech as speechsdk

                sub_maker = SubMaker()

                def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                    duration = _format_duration_to_offset(str(evt.duration))
                    offset = _format_duration_to_offset(evt.audio_offset)
                    sub_maker.subs.append(evt.text)
                    sub_maker.offset.append((offset, offset + duration))

                speech_key = config.azure.get("speech_key", "")
                service_region = config.azure.get("speech_region", "")
                if not speech_key or not service_region:
                    logger.error("Azure speech key or region is not set")
                    return None

                audio_config = speechsdk.audio.AudioOutputConfig(
                    filename=voice_file, use_default_speaker=True
                )
                speech_config = speechsdk.SpeechConfig(
                    subscription=speech_key, region=service_region
                )
                speech_config.speech_synthesis_voice_name = voice_name
                speech_config.set_property(
                    property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
                    value="true",
                )

                speech_config.set_speech_synthesis_output_format(
                    speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
                )
                speech_synthesizer = speechsdk.SpeechSynthesizer(
                    audio_config=audio_config, speech_config=speech_config
                )
                speech_synthesizer.synthesis_word_boundary.connect(
                    speech_synthesizer_word_boundary_cb
                )

                result = speech_synthesizer.speak_text_async(text).get()
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    logger.success(f"azure v2 speech synthesis succeeded: {voice_file}")
                    return sub_maker
                elif result.reason == speechsdk.ResultReason.Canceled:
                    cancellation_details = result.cancellation_details
                    logger.error(
                        f"azure v2 speech synthesis canceled: {cancellation_details.reason}"
                    )
                    if cancellation_details.reason == speechsdk.CancellationReason.Error:
                        logger.error(
                            f"azure v2 speech synthesis error: {cancellation_details.error_details}"
                        )
                logger.info(f"completed, output file: {voice_file}")
            except Exception as e:
                logger.error(f"failed, error: {str(e)}")
        return None
