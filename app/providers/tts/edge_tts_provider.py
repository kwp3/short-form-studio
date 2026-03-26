import asyncio
import re
from typing import List, Optional, Union

import edge_tts
from edge_tts import SubMaker
from loguru import logger

from app.providers import register_tts
from app.providers.base import TTSProvider


def _convert_rate_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0%"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}%"
    else:
        return f"{percent}%"


def get_all_azure_voices(filter_locals=None) -> list[str]:
    azure_voices_str = """
Name: en-AU-NatashaNeural
Gender: Female

Name: en-AU-WilliamNeural
Gender: Male

Name: en-CA-ClaraNeural
Gender: Female

Name: en-CA-LiamNeural
Gender: Male

Name: en-GB-LibbyNeural
Gender: Female

Name: en-GB-MaisieNeural
Gender: Female

Name: en-GB-RyanNeural
Gender: Male

Name: en-GB-SoniaNeural
Gender: Female

Name: en-GB-ThomasNeural
Gender: Male

Name: en-HK-SamNeural
Gender: Male

Name: en-HK-YanNeural
Gender: Female

Name: en-IE-ConnorNeural
Gender: Male

Name: en-IE-EmilyNeural
Gender: Female

Name: en-IN-NeerjaExpressiveNeural
Gender: Female

Name: en-IN-NeerjaNeural
Gender: Female

Name: en-IN-PrabhatNeural
Gender: Male

Name: en-KE-AsiliaNeural
Gender: Female

Name: en-KE-ChilembaNeural
Gender: Male

Name: en-NG-AbeoNeural
Gender: Male

Name: en-NG-EzinneNeural
Gender: Female

Name: en-NZ-MitchellNeural
Gender: Male

Name: en-NZ-MollyNeural
Gender: Female

Name: en-PH-JamesNeural
Gender: Male

Name: en-PH-RosaNeural
Gender: Female

Name: en-SG-LunaNeural
Gender: Female

Name: en-SG-WayneNeural
Gender: Male

Name: en-TZ-ElimuNeural
Gender: Male

Name: en-TZ-ImaniNeural
Gender: Female

Name: en-US-AnaNeural
Gender: Female

Name: en-US-AndrewMultilingualNeural
Gender: Male

Name: en-US-AndrewNeural
Gender: Male

Name: en-US-AriaNeural
Gender: Female

Name: en-US-AvaMultilingualNeural
Gender: Female

Name: en-US-AvaNeural
Gender: Female

Name: en-US-BrianMultilingualNeural
Gender: Male

Name: en-US-BrianNeural
Gender: Male

Name: en-US-ChristopherNeural
Gender: Male

Name: en-US-EmmaMultilingualNeural
Gender: Female

Name: en-US-EmmaNeural
Gender: Female

Name: en-US-EricNeural
Gender: Male

Name: en-US-GuyNeural
Gender: Male

Name: en-US-JennyNeural
Gender: Female

Name: en-US-MichelleNeural
Gender: Female

Name: en-US-RogerNeural
Gender: Male

Name: en-US-SteffanNeural
Gender: Male

Name: en-ZA-LeahNeural
Gender: Female

Name: en-ZA-LukeNeural
Gender: Male

Name: es-AR-ElenaNeural
Gender: Female

Name: es-AR-TomasNeural
Gender: Male

Name: es-CO-GonzaloNeural
Gender: Male

Name: es-CO-SalomeNeural
Gender: Female

Name: es-ES-AlvaroNeural
Gender: Male

Name: es-ES-ElviraNeural
Gender: Female

Name: es-ES-XimenaNeural
Gender: Female

Name: es-MX-DaliaNeural
Gender: Female

Name: es-MX-JorgeNeural
Gender: Male

Name: es-US-AlonsoNeural
Gender: Male

Name: en-US-AvaMultilingualNeural-V2
Gender: Female

Name: en-US-AndrewMultilingualNeural-V2
Gender: Male

Name: en-US-EmmaMultilingualNeural-V2
Gender: Female

Name: en-US-BrianMultilingualNeural-V2
Gender: Male
    """.strip()
    voices = []
    pattern = re.compile(r"Name:\s*(.+)\s*Gender:\s*(.+)\s*", re.MULTILINE)
    matches = pattern.findall(azure_voices_str)

    for name, gender in matches:
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    return voices


@register_tts
class EdgeTTSProvider(TTSProvider):
    @staticmethod
    def provider_name() -> str:
        return "edge"

    def get_voices(self) -> List[str]:
        return get_all_azure_voices()

    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        # Strip gender suffix from voice name
        voice_name = voice_name.replace("-Female", "").replace("-Male", "").strip()
        text = text.strip()
        rate_str = _convert_rate_to_percent(voice_rate)

        for i in range(3):
            try:
                logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

                async def _do() -> SubMaker:
                    communicate = edge_tts.Communicate(text, voice_name, rate=rate_str)
                    sub_maker = edge_tts.SubMaker()
                    with open(voice_file, "wb") as file:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                file.write(chunk["data"])
                            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                                sub_maker.feed(chunk)
                    return sub_maker

                sub_maker = asyncio.run(_do())
                # force compat shim to re-sync from .cues after feed()
                sub_maker._synced_from_cues = False
                if not sub_maker or not sub_maker.subs:
                    logger.warning("failed, sub_maker is None or sub_maker.subs is None")
                    continue

                logger.info(f"completed, output file: {voice_file}")
                return sub_maker
            except Exception as e:
                logger.error(f"failed, error: {str(e)}")
        return None
