import io
import logging
import wave
from collections.abc import Generator, Iterable
from itertools import chain
from typing import TYPE_CHECKING

from core.base.tts_audio_format import normalize_audio_mime_type, sniff_audio_mime_type
from core.base.tts_compatibility import is_tongyi_wav_model
from core.plugin.entities.plugin_daemon import TTSAudioChunk
from graphon.model_runtime.entities.model_entities import ModelPropertyKey
from graphon.model_runtime.errors.invoke import InvokeBadRequestError

if TYPE_CHECKING:
    from core.model_manager import ModelInstance


logger = logging.getLogger(__name__)

DEFAULT_TTS_AUDIO_MIME_TYPE = "audio/mpeg"
_SIGNATURE_SIZE = 32
_WAV_OUTPUT_CHUNK_SIZE = 64 * 1024


def get_model_audio_mime_type(model_instance: "ModelInstance") -> str | None:
    """Read the model's declared TTS MIME type without making it mandatory."""
    if is_tongyi_wav_model(
        getattr(model_instance, "provider", ""),
        getattr(model_instance, "model_name", ""),
    ):
        # tongyi 0.2.4 declares MP3 for qwen3-tts-flash, while DashScope returns
        # complete WAV containers. Treating it as MP3 enables incremental output
        # and makes multiple WAV files get concatenated into an invalid payload.
        return "audio/wav"

    try:
        model_schema = model_instance.get_model_schema()
        audio_type = model_schema.model_properties.get(ModelPropertyKey.AUDIO_TYPE)
    except Exception:
        logger.debug("Unable to resolve the declared audio type for the TTS model", exc_info=True)
        return None

    return normalize_audio_mime_type(audio_type)


def _normalize_reported_mime_type(mime_type: object | None, source: str) -> str | None:
    if mime_type is None:
        return None

    normalized_mime_type = normalize_audio_mime_type(mime_type)
    if normalized_mime_type is None:
        raise InvokeBadRequestError(f"TTS provider returned an unsupported {source} MIME type: {mime_type!r}")
    return normalized_mime_type


def _extract_audio_chunk(chunk: bytes | bytearray | memoryview | TTSAudioChunk) -> tuple[bytes, str | None]:
    """Accept old byte chunks and the compatibility carrier for current Graphon."""
    if isinstance(chunk, TTSAudioChunk):
        return bytes(chunk), chunk.mime_type

    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return bytes(chunk), None

    raise InvokeBadRequestError("TTS provider returned a chunk that is not audio bytes")


def resolve_audio_mime_type(
    audio: bytes | bytearray | memoryview,
    declared_mime_type: str | None = None,
    reported_mime_type: str | None = None,
) -> str:
    """Validate the provider MIME against magic bytes and choose the true type.

    ``reported_mime_type`` is emitted with a TTS chunk by current plugin
    runtimes, and therefore takes precedence over schema metadata. Schema
    metadata remains a fallback for old plugins that omit the new field.
    """
    normalized_declared_mime_type = _normalize_reported_mime_type(declared_mime_type, "schema")
    normalized_reported_mime_type = _normalize_reported_mime_type(reported_mime_type, "chunk")
    detected_mime_type = sniff_audio_mime_type(audio)

    expected_mime_type = normalized_reported_mime_type or normalized_declared_mime_type
    if expected_mime_type and detected_mime_type and expected_mime_type != detected_mime_type:
        raise InvokeBadRequestError(
            "TTS provider output MIME does not match its audio bytes: "
            f"declared {expected_mime_type}, detected {detected_mime_type}"
        )

    if normalized_reported_mime_type:
        if normalized_declared_mime_type and normalized_declared_mime_type != normalized_reported_mime_type:
            logger.info(
                "TTS chunk MIME %s overrides schema MIME %s",
                normalized_reported_mime_type,
                normalized_declared_mime_type,
            )
        return normalized_reported_mime_type

    if detected_mime_type:
        return detected_mime_type

    return normalized_declared_mime_type or DEFAULT_TTS_AUDIO_MIME_TYPE


def _split_concatenated_wav(audio: bytes) -> list[bytes] | None:
    """Split adjacent RIFF/WAVE containers, returning ``None`` for a single WAV."""
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None

    segments: list[bytes] = []
    offset = 0
    while offset < len(audio):
        remaining = len(audio) - offset
        if remaining < 12 or audio[offset : offset + 4] != b"RIFF" or audio[offset + 8 : offset + 12] != b"WAVE":
            if not segments:
                return None
            raise InvokeBadRequestError("TTS provider returned malformed concatenated WAV audio")

        segment_size = int.from_bytes(audio[offset + 4 : offset + 8], byteorder="little") + 8
        if segment_size < 12 or segment_size > remaining:
            if not segments:
                # Preserve the existing behavior for providers whose single WAV
                # has an inaccurate RIFF size; browsers may still accept it.
                return None
            raise InvokeBadRequestError("TTS provider returned a truncated WAV segment")

        segment_end = offset + segment_size
        segments.append(audio[offset:segment_end])
        offset = segment_end

    return segments if len(segments) > 1 else None


def merge_concatenated_wav(audio: bytes) -> bytes:
    """Turn adjacent complete WAV files into one browser-playable WAV file."""
    segments = _split_concatenated_wav(audio)
    if segments is None:
        return audio

    return _merge_wav_segments(segments)


def _merge_wav_segments(segments: list[bytes]) -> bytes:
    """Merge WAV containers whose boundaries are already known."""
    if len(segments) == 1:
        return segments[0]

    expected_format: tuple[int, int, int, str] | None = None
    frames: list[bytes] = []
    try:
        for segment in segments:
            with wave.open(io.BytesIO(segment), "rb") as reader:
                current_format = (
                    reader.getnchannels(),
                    reader.getsampwidth(),
                    reader.getframerate(),
                    reader.getcomptype(),
                )
                if current_format[3] != "NONE":
                    raise InvokeBadRequestError("TTS WAV segments must contain uncompressed PCM audio")
                if expected_format is None:
                    expected_format = current_format
                elif current_format != expected_format:
                    raise InvokeBadRequestError("TTS WAV segments use incompatible audio formats")
                frames.append(reader.readframes(reader.getnframes()))
    except (EOFError, wave.Error) as e:
        raise InvokeBadRequestError("TTS provider returned malformed WAV audio") from e

    if expected_format is None:
        return audio

    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        channels, sample_width, frame_rate, _ = expected_format
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(frame_rate)
        for frame_data in frames:
            writer.writeframesraw(frame_data)
    return output.getvalue()


def inspect_audio_stream(
    audio_stream: Iterable[bytes | bytearray | memoryview | TTSAudioChunk], declared_mime_type: str | None = None
) -> tuple[Generator[bytes, None, None], str]:
    """Peek at and validate a TTS stream without dropping its leading bytes."""
    iterator = iter(audio_stream)
    leading_chunks: list[bytes] = []
    signature = bytearray()
    reported_mime_type: str | None = None

    while len(signature) < _SIGNATURE_SIZE:
        try:
            chunk, chunk_mime_type = _extract_audio_chunk(next(iterator))
        except StopIteration:
            break
        normalized_chunk_mime_type = _normalize_reported_mime_type(chunk_mime_type, "chunk")
        if normalized_chunk_mime_type:
            if reported_mime_type and reported_mime_type != normalized_chunk_mime_type:
                raise InvokeBadRequestError(
                    "TTS provider changed MIME type within one audio response: "
                    f"{reported_mime_type} then {normalized_chunk_mime_type}"
                )
            reported_mime_type = normalized_chunk_mime_type
        leading_chunks.append(chunk)
        signature.extend(chunk[: _SIGNATURE_SIZE - len(signature)])

    mime_type = resolve_audio_mime_type(signature, declared_mime_type, reported_mime_type)

    def validated_stream() -> Generator[bytes, None, None]:
        for chunk in chain(leading_chunks, iterator):
            audio, chunk_mime_type = _extract_audio_chunk(chunk)
            normalized_chunk_mime_type = _normalize_reported_mime_type(chunk_mime_type, "chunk")
            if normalized_chunk_mime_type and normalized_chunk_mime_type != mime_type:
                raise InvokeBadRequestError(
                    "TTS provider changed MIME type within one audio response: "
                    f"{mime_type} then {normalized_chunk_mime_type}"
                )
            yield audio

    if mime_type == "audio/wav":

        def normalized_wav_stream() -> Generator[bytes, None, None]:
            audio_chunks = list(validated_stream())
            if audio_chunks:
                if len(audio_chunks) > 1 and all(
                    len(chunk) >= 12 and chunk[:4] == b"RIFF" and chunk[8:12] == b"WAVE" for chunk in audio_chunks
                ):
                    # Tongyi uses a sentinel RIFF length instead of the real
                    # container size. Preserve provider chunk boundaries so
                    # those complete WAV files can still be merged correctly.
                    normalized_audio = _merge_wav_segments(audio_chunks)
                else:
                    normalized_audio = merge_concatenated_wav(b"".join(audio_chunks))
                for offset in range(0, len(normalized_audio), _WAV_OUTPUT_CHUNK_SIZE):
                    yield normalized_audio[offset : offset + _WAV_OUTPUT_CHUNK_SIZE]

        return normalized_wav_stream(), mime_type

    return validated_stream(), mime_type
