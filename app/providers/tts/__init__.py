# TTS provider auto-imports — each provider registers itself via @register_tts
from app.providers.tts.edge_tts_provider import EdgeTTSProvider  # noqa: F401
from app.providers.tts.azure_cognitive import AzureCognitiveProvider  # noqa: F401
from app.providers.tts.siliconflow import SiliconFlowProvider  # noqa: F401
from app.providers.tts.gemini_tts import GeminiTTSProvider  # noqa: F401
