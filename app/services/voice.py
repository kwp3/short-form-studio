import os
import re
from typing import Union
from xml.sax.saxutils import unescape

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

# Import providers AFTER the shim so SubMaker is patched before any provider uses it
import app.providers.tts  # noqa: E402, F401 — triggers registration of all TTS providers
from app.providers import get_tts_provider
from app.providers.tts.edge_tts_provider import get_all_azure_voices  # re-export for backward compat
from app.providers.tts.siliconflow import get_siliconflow_voices  # re-export
from app.providers.tts.gemini_tts import get_gemini_voices  # re-export

from moviepy.video.tools import subtitles
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.utils import utils


# ── Voice name helpers ──────────────────────────────────────────

def parse_voice_name(name: str):
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


def _detect_tts_provider(voice_name: str) -> str:
    if is_azure_v2_voice(voice_name):
        return "azure_cognitive"
    elif is_siliconflow_voice(voice_name):
        return "siliconflow"
    elif is_gemini_voice(voice_name):
        return "gemini"
    return "edge"


# ── Main TTS facade ────────────────────────────────────────────

def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    provider_key = _detect_tts_provider(voice_name)
    provider = get_tts_provider(provider_key)
    return provider.synthesize(text, voice_name, voice_rate, voice_file, voice_volume)


# ── Text formatting ─────────────────────────────────────────────

def _format_text(text: str) -> str:
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    text = text.strip()
    return text


# ── Subtitle creation ──────────────────────────────────────────

def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):
    """
    Optimize subtitle file:
    1. Split subtitle file into multiple lines by punctuation
    2. Match text in subtitle file line by line
    3. Generate new subtitle file
    """

    text = _format_text(text)

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
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


# ── Audio duration helpers ─────────────────────────────────────

def _get_audio_duration_from_submaker(sub_maker: submaker.SubMaker):
    if not sub_maker.offset:
        return 0.0
    return sub_maker.offset[-1][1] / 10000000


def _get_audio_duration_from_mp3(mp3_file: str) -> float:
    if not os.path.exists(mp3_file):
        logger.error(f"MP3 file does not exist: {mp3_file}")
        return 0.0

    try:
        with AudioFileClip(mp3_file) as audio:
            return audio.duration
    except Exception as e:
        logger.error(f"Failed to get audio duration from MP3: {str(e)}")
        return 0.0


def get_audio_duration(target: Union[str, submaker.SubMaker]) -> float:
    if isinstance(target, submaker.SubMaker):
        return _get_audio_duration_from_submaker(target)
    elif isinstance(target, str) and target.endswith(".mp3"):
        return _get_audio_duration_from_mp3(target)
    else:
        logger.error(f"Invalid target type: {type(target)}")
        return 0.0
