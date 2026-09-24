_SIGNATURE_SIZE = 32
_AUDIO_MIME_TYPE_ALIASES = {
    "mp3": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/mpeg": "audio/mpeg",
    "wav": "audio/wav",
    "wave": "audio/wav",
    "audio/wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "audio/ogg": "audio/ogg",
    "flac": "audio/flac",
    "audio/flac": "audio/flac",
    "aac": "audio/aac",
    "audio/aac": "audio/aac",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "audio/mp4": "audio/mp4",
    "webm": "audio/webm",
    "audio/webm": "audio/webm",
}


def normalize_audio_mime_type(audio_type: object | None) -> str | None:
    """Convert provider audio-type metadata into a browser MIME type."""
    if not isinstance(audio_type, str):
        return None

    mime_type = audio_type.split(";", maxsplit=1)[0].strip().lower()
    return _AUDIO_MIME_TYPE_ALIASES.get(mime_type)


def sniff_audio_mime_type(audio: bytes | bytearray | memoryview) -> str | None:
    """Identify common audio containers from their leading bytes."""
    signature = bytes(audio[:_SIGNATURE_SIZE])
    if len(signature) >= 12 and signature[:4] == b"RIFF" and signature[8:12] == b"WAVE":
        return "audio/wav"
    if signature.startswith(b"OggS"):
        return "audio/ogg"
    if signature.startswith(b"fLaC"):
        return "audio/flac"
    if signature.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm"
    if len(signature) >= 8 and signature[4:8] == b"ftyp":
        return "audio/mp4"
    if len(signature) >= 2 and signature[0] == 0xFF:
        if signature[1] & 0xF6 == 0xF0:
            return "audio/aac"
        if signature[1] & 0xE0 == 0xE0:
            return "audio/mpeg"
    return None
