from abc import ABC, abstractmethod
from typing import List, Optional

from edge_tts import SubMaker


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
    ) -> Optional[SubMaker]:
        ...

    @abstractmethod
    def get_voices(self) -> List[str]:
        ...

    @staticmethod
    @abstractmethod
    def provider_name() -> str:
        ...


class MaterialProvider(ABC):
    @abstractmethod
    def search_videos(
        self, search_term: str, minimum_duration: int, video_aspect
    ) -> list:
        ...

    @staticmethod
    @abstractmethod
    def provider_name() -> str:
        ...
