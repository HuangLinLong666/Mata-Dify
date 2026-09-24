_TONGYI_WAV_MODELS = frozenset({"qwen3-tts-flash"})
# qwen3-tts-flash calls around 400 Chinese characters can outlive the Tongyi
# plugin subprocess. Keep each request short enough to match the stable preview
# path; the resulting WAV containers are merged by ``inspect_audio_stream``.
TONGYI_TTS_REQUEST_CHAR_LIMIT = 80
_TTS_SENTENCE_ENDINGS = ("。", "！", "？", "!", "?", ".", ";", "；", "\n")


def is_tongyi_wav_model(provider: object, model_name: object) -> bool:
    """Return whether a model needs the Tongyi qwen3 WAV compatibility path."""
    provider_name = str(provider).lower()
    normalized_model_name = str(model_name).lower()
    return "tongyi" in provider_name.split("/") and normalized_model_name in _TONGYI_WAV_MODELS


def split_tts_text(text: str, max_length: int = TONGYI_TTS_REQUEST_CHAR_LIMIT) -> list[str]:
    """Split TTS text at sentence boundaries without exceeding ``max_length``."""
    if max_length <= 0:
        raise ValueError("max_length must be greater than zero")

    remaining = text.strip()
    chunks: list[str] = []
    while len(remaining) > max_length:
        window = remaining[:max_length]
        split_at = max((window.rfind(ending) + 1 for ending in _TTS_SENTENCE_ENDINGS), default=0)
        if split_at == 0:
            split_at = max_length
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks
