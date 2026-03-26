import asyncio
import os
import re
from datetime import datetime
from typing import Union
from xml.sax.saxutils import unescape

import edge_tts
import requests
from edge_tts import SubMaker, submaker
from loguru import logger


def mktimestamp(ns100: int) -> str:
    """Convert 100-nanosecond ticks to SRT-style timestamp HH:MM:SS.mmm"""
    ms = int(ns100 / 10000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ── edge-tts v7 compatibility shim ──────────────────────────────
# v7 replaced SubMaker.create_sub/.subs/.offset with feed()/.cues.
# Patch the class so all existing code paths keep working:
#   - .subs  (mutable list of strings)
#   - .offset (mutable list of (start, end) tuples in 100ns ticks)
#   - .append() on both works correctly
#   - After feed() populates .cues, first read lazily syncs to compat lists
if not hasattr(SubMaker, "_compat_subs"):
    _orig_init = SubMaker.__init__

    def _patched_init(self):
        _orig_init(self)
        self._compat_subs = []
        self._compat_offset = []
        self._synced_from_cues = False

    SubMaker.__init__ = _patched_init

    def _sync_from_cues(self):
        """Lazily pull data from .cues into compat lists (one-time)."""
        if not self._synced_from_cues and self.cues:
            self._compat_subs = [c.content for c in self.cues]
            self._compat_offset = [
                (int(c.start.total_seconds() * 1e7), int(c.end.total_seconds() * 1e7))
                for c in self.cues
            ]
            self._synced_from_cues = True

    @property
    def _subs_prop(self):
        _sync_from_cues(self)
        return self._compat_subs

    @_subs_prop.setter
    def _subs_prop(self, value):
        self._compat_subs = value
        self._synced_from_cues = True

    @property
    def _offset_prop(self):
        _sync_from_cues(self)
        return self._compat_offset

    @_offset_prop.setter
    def _offset_prop(self, value):
        self._compat_offset = value
        self._synced_from_cues = True

    SubMaker.subs = _subs_prop
    SubMaker.offset = _offset_prop
# ── end shim ────────────────────────────────────────────────────
from moviepy.video.tools import subtitles
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.config import config
from app.utils import utils


def get_siliconflow_voices() -> list[str]:
    """
    Get the list of SiliconFlow voices.

    Returns:
        Voice list, format: ["siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex", ...]
    """
    # SiliconFlow voice list with corresponding gender (for display)
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

    # Add siliconflow: prefix and format as display name
    return [
        f"siliconflow:{model}:{voice}-{gender}"
        for model, voice, gender in voices_with_gender
    ]


def get_gemini_voices() -> list[str]:
    """
    Get the list of Gemini TTS voices.

    Returns:
        Voice list, format: ["gemini:Zephyr-Female", "gemini:Puck-Male", ...]
    """
    # Gemini TTS supported voice list
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
    
    # Add gemini: prefix and format as display name
    return [
        f"gemini:{voice}-{gender}"
        for voice, gender in voices_with_gender
    ]


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
    # Define regex pattern to match Name and Gender lines
    pattern = re.compile(r"Name:\s*(.+)\s*Gender:\s*(.+)\s*", re.MULTILINE)
    # Find all matches using regex
    matches = pattern.findall(azure_voices_str)

    for name, gender in matches:
        # Apply filter conditions
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    return voices


def parse_voice_name(name: str):
    # zh-CN-XiaoyiNeural-Female
    # zh-CN-YunxiNeural-Male
    # zh-CN-XiaoxiaoMultilingualNeural-V2-Female
    name = name.replace("-Female", "").replace("-Male", "").strip()
    return name


def is_azure_v2_voice(voice_name: str):
    voice_name = parse_voice_name(voice_name)
    if voice_name.endswith("-V2"):
        return voice_name.replace("-V2", "").strip()
    return ""


def is_siliconflow_voice(voice_name: str):
    """Check if it is a SiliconFlow voice"""
    return voice_name.startswith("siliconflow:")


def is_gemini_voice(voice_name: str):
    """Check if it is a Gemini TTS voice"""
    return voice_name.startswith("gemini:")


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    if is_azure_v2_voice(voice_name):
        return azure_tts_v2(text, voice_name, voice_file)
    elif is_siliconflow_voice(voice_name):
        # Extract model and voice from voice_name
        # Format: siliconflow:model:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 3:
            model = parts[1]
            # Remove gender suffix, e.g. "alex-Male" -> "alex"
            voice_with_gender = parts[2]
            voice = voice_with_gender.split("-")[0]
            # Build full voice parameter, format: "model:voice"
            full_voice = f"{model}:{voice}"
            return siliconflow_tts(
                text, model, full_voice, voice_rate, voice_file, voice_volume
            )
        else:
            logger.error(f"Invalid siliconflow voice name format: {voice_name}")
            return None
    elif is_gemini_voice(voice_name):
        # Extract voice name from voice_name
        # Format: gemini:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 2:
            # Remove gender suffix, e.g. "Zephyr-Female" -> "Zephyr"
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return gemini_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid gemini voice name format: {voice_name}")
            return None
    return azure_tts_v1(text, voice_name, voice_rate, voice_file)


def convert_rate_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0%"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}%"
    else:
        return f"{percent}%"


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_file: str
) -> Union[SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
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


def siliconflow_tts(
    text: str,
    model: str,
    voice: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    Generate speech using the SiliconFlow API.

    Args:
        text: Text to convert to speech
        model: Model name, e.g. "FunAudioLLM/CosyVoice2-0.5B"
        voice: Voice name, e.g. "FunAudioLLM/CosyVoice2-0.5B:alex"
        voice_rate: Speech speed, range [0.25, 4.0]
        voice_file: Output audio file path
        voice_volume: Voice volume, range [0.6, 5.0], converted to SiliconFlow gain range [-10, 10]

    Returns:
        SubMaker object or None
    """
    text = text.strip()
    api_key = config.siliconflow.get("api_key", "")

    if not api_key:
        logger.error("SiliconFlow API key is not set")
        return None

    # Convert voice_volume to SiliconFlow gain range
    # Default voice_volume is 1.0, corresponding to gain of 0
    gain = voice_volume - 1.0
    # Ensure gain is within [-10, 10] range
    gain = max(-10, min(10, gain))

    url = "https://api.siliconflow.cn/v1/audio/speech"

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "sample_rate": 32000,
        "stream": False,
        "speed": voice_rate,
        "gain": gain,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for i in range(3):  # Try 3 times
        try:
            logger.info(
                f"start siliconflow tts, model: {model}, voice: {voice}, try: {i + 1}"
            )

            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                # Save audio file
                with open(voice_file, "wb") as f:
                    f.write(response.content)

                # Create an empty SubMaker object
                sub_maker = SubMaker()

                # Get the actual length of the audio file
                try:
                    # Try using moviepy to get audio length
                    from moviepy import AudioFileClip

                    audio_clip = AudioFileClip(voice_file)
                    audio_duration = audio_clip.duration
                    audio_clip.close()

                    # Convert audio length to 100-nanosecond units (compatible with edge_tts)
                    audio_duration_100ns = int(audio_duration * 10000000)

                    # Use text splitting to create more accurate subtitles
                    # Split text into sentences by punctuation
                    sentences = utils.split_string_by_punctuations(text)

                    if sentences:
                        # Calculate approximate duration for each sentence (proportional to character count)
                        total_chars = sum(len(s) for s in sentences)
                        char_duration = (
                            audio_duration_100ns / total_chars if total_chars > 0 else 0
                        )

                        current_offset = 0
                        for sentence in sentences:
                            if not sentence.strip():
                                continue

                            # Calculate duration of current sentence
                            sentence_chars = len(sentence)
                            sentence_duration = int(sentence_chars * char_duration)

                            # Add to SubMaker
                            sub_maker.subs.append(sentence)
                            sub_maker.offset.append(
                                (current_offset, current_offset + sentence_duration)
                            )

                            # Update offset
                            current_offset += sentence_duration
                    else:
                        # If splitting fails, use the entire text as one subtitle
                        sub_maker.subs = [text]
                        sub_maker.offset = [(0, audio_duration_100ns)]

                except Exception as e:
                    logger.warning(f"Failed to create accurate subtitles: {str(e)}")
                    # Fallback to simple subtitle
                    sub_maker.subs = [text]
                    # Use the actual audio file length; if unavailable, assume 10 seconds
                    sub_maker.offset = [
                        (
                            0,
                            audio_duration_100ns
                            if "audio_duration_100ns" in locals()
                            else 10000000,
                        )
                    ]

                logger.success(f"siliconflow tts succeeded: {voice_file}")
                print("s", sub_maker.subs, sub_maker.offset)
                return sub_maker
            else:
                logger.error(
                    f"siliconflow tts failed with status code {response.status_code}: {response.text}"
                )
        except Exception as e:
            logger.error(f"siliconflow tts failed: {str(e)}")

    return None


def azure_tts_v2(text: str, voice_name: str, voice_file: str) -> Union[SubMaker, None]:
    voice_name = is_azure_v2_voice(voice_name)
    if not voice_name:
        logger.error(f"invalid voice name: {voice_name}")
        raise ValueError(f"invalid voice name: {voice_name}")
    text = text.strip()

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

    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            import azure.cognitiveservices.speech as speechsdk

            sub_maker = SubMaker()

            def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                # print('WordBoundary event:')
                # print('\tBoundaryType: {}'.format(evt.boundary_type))
                # print('\tAudioOffset: {}ms'.format((evt.audio_offset + 5000)))
                # print('\tDuration: {}'.format(evt.duration))
                # print('\tText: {}'.format(evt.text))
                # print('\tTextOffset: {}'.format(evt.text_offset))
                # print('\tWordLength: {}'.format(evt.word_length))

                duration = _format_duration_to_offset(str(evt.duration))
                offset = _format_duration_to_offset(evt.audio_offset)
                sub_maker.subs.append(evt.text)
                sub_maker.offset.append((offset, offset + duration))

            # Creates an instance of a speech config with specified subscription key and service region.
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
            # speech_config.set_property(property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
            #                            value='true')
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


def gemini_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    Generate speech using Google Gemini TTS.

    Args:
        text: Text to convert
        voice_name: Voice name, e.g. "Zephyr", "Puck", etc.
        voice_rate: Speech rate (currently unused)
        voice_file: Output audio file path
        voice_volume: Audio volume (currently unused)

    Returns:
        SubMaker object or None
    """
    import base64
    import json
    import io
    from pydub import AudioSegment
    import google.generativeai as genai
    
    try:
        # Configure Gemini API
        api_key = config.app.get("gemini_api_key", "")
        if not api_key:
            logger.error("Gemini API key is not set")
            return None
            
        genai.configure(api_key=api_key)
        
        logger.info(f"start, voice name: {voice_name}, try: 1")
        
        # Use Gemini TTS API
        model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")
        
        generation_config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": voice_name
                    }
                }
            }
        }
        
        response = model.generate_content(
            contents=text,
            generation_config=generation_config
        )
        
        # Check response
        if not response.candidates or not response.candidates[0].content:
            logger.error("No audio content received from Gemini TTS")
            return None
            
        # Get audio data
        audio_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                break
                
        if not audio_data:
            logger.error("No audio data found in response")
            return None
            
        # Audio data is already raw bytes, no base64 decoding needed
        if isinstance(audio_data, str):
            # If it's a string, base64 decoding is needed
            audio_bytes = base64.b64decode(audio_data)
        else:
            # If already bytes, use directly
            audio_bytes = audio_data
        
        # Try different audio formats - Gemini may return different formats
        audio_segment = None
        
        # Gemini returns Linear PCM format, parse according to documentation parameters
        try:
            audio_segment = AudioSegment.from_file(
                io.BytesIO(audio_bytes), 
                format="raw",
                frame_rate=24000,  # Gemini TTS default sample rate
                channels=1,        # Mono
                sample_width=2     # 16-bit
            )
        except Exception as e:
            logger.error(f"Failed to load PCM audio: {e}")
            return None
        
        # Export as MP3 format
        audio_segment.export(voice_file, format="mp3")
        
        logger.info(f"completed, output file: {voice_file}")
        
        # Create SubMaker object for subtitles
        sub_maker = SubMaker()
        audio_duration = len(audio_segment) / 1000.0  # Convert to seconds
        
        # Convert audio length to 100-nanosecond units (compatible with edge_tts)
        audio_duration_100ns = int(audio_duration * 10000000)
        
        # Populate subtitle data via compat shim (edge-tts v7)
        sub_maker.subs = [text]
        sub_maker.offset = [(0, audio_duration_100ns)]
        
        return sub_maker
        
    except ImportError as e:
        logger.error(f"Missing required package for Gemini TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Gemini TTS failed, error: {str(e)}")
        return None


def _format_text(text: str) -> str:
    # text = text.replace("\n", " ")
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    text = text.strip()
    return text


def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):
    """
    Optimize subtitle file:
    1. Split subtitle file into multiple lines by punctuation
    2. Match text in subtitle file line by line
    3. Generate new subtitle file
    """

    text = _format_text(text)

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        """
        1
        00:00:00,000 --> 00:00:02,360
        Running is a simple and easy exercise
        """
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    start_time = -1.0
    sub_items = []
    sub_index = 0

    script_lines = utils.split_string_by_punctuations(text)

    def match_line(_sub_line: str, _sub_index: int):
        if len(script_lines) <= _sub_index:
            return ""

        _line = script_lines[_sub_index]
        if _sub_line == _line:
            return script_lines[_sub_index].strip()

        _sub_line_ = re.sub(r"[^\w\s]", "", _sub_line)
        _line_ = re.sub(r"[^\w\s]", "", _line)
        if _sub_line_ == _line_:
            return _line_.strip()

        _sub_line_ = re.sub(r"\W+", "", _sub_line)
        _line_ = re.sub(r"\W+", "", _line)
        if _sub_line_ == _line_:
            return _line.strip()

        return ""

    sub_line = ""

    try:
        for _, (offset, sub) in enumerate(zip(sub_maker.offset, sub_maker.subs)):
            _start_time, end_time = offset
            if start_time < 0:
                start_time = _start_time

            sub = unescape(sub)
            sub_line += sub
            sub_text = match_line(sub_line, sub_index)
            if sub_text:
                sub_index += 1
                line = formatter(
                    idx=sub_index,
                    start_time=start_time,
                    end_time=end_time,
                    sub_text=sub_text,
                )
                sub_items.append(line)
                start_time = -1.0
                sub_line = ""

        if len(sub_items) == len(script_lines):
            with open(subtitle_file, "w", encoding="utf-8") as file:
                file.write("\n".join(sub_items) + "\n")
            try:
                sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
                duration = max([tb for ((ta, tb), txt) in sbs])
                logger.info(
                    f"completed, subtitle file created: {subtitle_file}, duration: {duration}"
                )
            except Exception as e:
                logger.error(f"failed, error: {str(e)}")
                os.remove(subtitle_file)
        else:
            logger.warning(
                f"failed, sub_items len: {len(sub_items)}, script_lines len: {len(script_lines)}"
            )

    except Exception as e:
        logger.error(f"failed, error: {str(e)}")


def _get_audio_duration_from_submaker(sub_maker: submaker.SubMaker):
    """
    Get audio duration from SubMaker object.
    """
    if not sub_maker.offset:
        return 0.0
    return sub_maker.offset[-1][1] / 10000000

def _get_audio_duration_from_mp3(mp3_file: str) -> float:
    """
    Get MP3 audio duration.
    """
    if not os.path.exists(mp3_file):
        logger.error(f"MP3 file does not exist: {mp3_file}")
        return 0.0

    try:
        # Use moviepy to get the duration of the MP3 file
        with AudioFileClip(mp3_file) as audio:
            return audio.duration  # Duration in seconds
    except Exception as e:
        logger.error(f"Failed to get audio duration from MP3: {str(e)}")
        return 0.0

def get_audio_duration( target: Union[str, submaker.SubMaker]) -> float:
    """
    Get audio duration.
    If target is a SubMaker object, get duration from SubMaker.
    If target is an MP3 file, get duration from the MP3 file.
    """
    if isinstance(target, submaker.SubMaker):
        return _get_audio_duration_from_submaker(target)
    elif isinstance(target, str) and target.endswith(".mp3"):
        return _get_audio_duration_from_mp3(target)
    else:
        logger.error(f"Invalid target type: {type(target)}")
        return 0.0

if __name__ == "__main__":
    voice_name = "zh-CN-XiaoxiaoMultilingualNeural-V2-Female"
    voice_name = parse_voice_name(voice_name)
    voice_name = is_azure_v2_voice(voice_name)
    print(voice_name)

    voices = get_all_azure_voices()
    print(len(voices))

    async def _do():
        temp_dir = utils.storage_dir("temp")

        voice_names = [
            "zh-CN-XiaoxiaoMultilingualNeural",
            # Female
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            # Male
            "zh-CN-YunyangNeural",
            "zh-CN-YunxiNeural",
        ]
        text = “””
        Quiet Night Thoughts is a famous five-character ancient poem written by Li Bai, a Tang Dynasty poet. The poem depicts the poet on a quiet night, seeing the bright moon outside his window, and feeling a deep longing for his faraway hometown and loved ones.
            “””

        text = """
        What is the meaning of life? This question has puzzled philosophers, scientists, and thinkers of all kinds for centuries. Throughout history, various cultures and individuals have come up with their interpretations and beliefs around the purpose of life. Some say it's to seek happiness and self-fulfillment, while others believe it's about contributing to the welfare of others and making a positive impact in the world. Despite the myriad of perspectives, one thing remains clear: the meaning of life is a deeply personal concept that varies from one person to another. It's an existential inquiry that encourages us to reflect on our values, desires, and the essence of our existence.
        """

        text = """
               Frequent cold air activity is expected over the next 3 days. Overcast skies with light rain for the next two days, bring rain gear when going out.
               Continued overcast with light rain on the 10th-11th, small daily temperature range, temperatures between 13-17 degrees Celsius, feeling cool.
               Weather will briefly improve on the 12th, cool mornings and evenings.
                   """

        text = "[Opening scene: A sunny day in a suburban neighborhood. A young boy named Alex, around 8 years old, is playing in his front yard with his loyal dog, Buddy.]\n\n[Camera zooms in on Alex as he throws a ball for Buddy to fetch. Buddy excitedly runs after it and brings it back to Alex.]\n\nAlex: Good boy, Buddy! You're the best dog ever!\n\n[Buddy barks happily and wags his tail.]\n\n[As Alex and Buddy continue playing, a series of potential dangers loom nearby, such as a stray dog approaching, a ball rolling towards the street, and a suspicious-looking stranger walking by.]\n\nAlex: Uh oh, Buddy, look out!\n\n[Buddy senses the danger and immediately springs into action. He barks loudly at the stray dog, scaring it away. Then, he rushes to retrieve the ball before it reaches the street and gently nudges it back towards Alex. Finally, he stands protectively between Alex and the stranger, growling softly to warn them away.]\n\nAlex: Wow, Buddy, you're like my superhero!\n\n[Just as Alex and Buddy are about to head inside, they hear a loud crash from a nearby construction site. They rush over to investigate and find a pile of rubble blocking the path of a kitten trapped underneath.]\n\nAlex: Oh no, Buddy, we have to help!\n\n[Buddy barks in agreement and together they work to carefully move the rubble aside, allowing the kitten to escape unharmed. The kitten gratefully nuzzles against Buddy, who responds with a friendly lick.]\n\nAlex: We did it, Buddy! We saved the day again!\n\n[As Alex and Buddy walk home together, the sun begins to set, casting a warm glow over the neighborhood.]\n\nAlex: Thanks for always being there to watch over me, Buddy. You're not just my dog, you're my best friend.\n\n[Buddy barks happily and nuzzles against Alex as they disappear into the sunset, ready to face whatever adventures tomorrow may bring.]\n\n[End scene.]"

        text = "Hello everyone, today we are going to talk about credit card cash withdrawal features.\nHave you ever used your credit card at an ATM to withdraw cash due to a temporary financial crunch? If so, you should watch this video.\nCredit card cash withdrawals have three major drawbacks.\nFirst, the cost is not small. There is a cash withdrawal fee, for example, withdrawing 10,000 at 2.5% means a 250 fee.\nSecond, normal credit card purchases enjoy up to 56 days of interest-free period, but cash withdrawals do not. Interest is charged daily from the day of withdrawal.\nThird, frequent cash withdrawals will cause the bank to flag you as a high-risk user, affecting your credit score and credit limit."

        text = """
        2023 Full Year Performance Overview
The company achieved cumulative operating revenue of 147.694 billion yuan for the full year, a year-on-year increase of 19.01%, with net profit attributable to shareholders of 74.734 billion yuan, up 19.16% year-on-year. EPS reached 59.49 yuan. In Q4 alone, operating revenue was 44.425 billion yuan, up 20.26% year-on-year and 31.86% quarter-on-quarter.
2023 Q4 Performance Overview
In Q4, operating revenue was the main growth driver; high growth in sales expenses put pressure on profitability; taxes rose 27% year-on-year, affecting net profit margin.
Performance Analysis
Regarding profits, the full-year 2023 net profit growth rate was 19%, with operating revenue contributing 18% positive growth, operating costs contributing 1%, and management expenses contributing 1.4%.
"""
        text = "Quiet Night Thoughts is a famous poem by Li Bai. It depicts the poet on a quiet night, seeing the bright moon and feeling a deep longing for his faraway hometown and loved ones."

        text = _format_text(text)
        lines = utils.split_string_by_punctuations(text)
        print(lines)

        for voice_name in voice_names:
            voice_file = f"{temp_dir}/tts-{voice_name}.mp3"
            subtitle_file = f"{temp_dir}/tts.mp3.srt"
            sub_maker = azure_tts_v2(
                text=text, voice_name=voice_name, voice_file=voice_file
            )
            create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
            audio_duration = get_audio_duration(sub_maker)
            print(f"voice: {voice_name}, audio duration: {audio_duration}s")

    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()
