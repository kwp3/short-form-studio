from app.providers.base import TTSProvider, MaterialProvider

_tts_registry: dict[str, type[TTSProvider]] = {}
_material_registry: dict[str, type[MaterialProvider]] = {}


def register_tts(cls):
    _tts_registry[cls.provider_name()] = cls
    return cls


def register_material(cls):
    _material_registry[cls.provider_name()] = cls
    return cls


def get_tts_provider(name: str) -> TTSProvider:
    if name not in _tts_registry:
        raise ValueError(
            f"Unknown TTS provider: {name!r}. "
            f"Available: {list(_tts_registry.keys())}"
        )
    return _tts_registry[name]()


def get_material_provider(name: str) -> MaterialProvider:
    if name not in _material_registry:
        raise ValueError(
            f"Unknown material provider: {name!r}. "
            f"Available: {list(_material_registry.keys())}"
        )
    return _material_registry[name]()
