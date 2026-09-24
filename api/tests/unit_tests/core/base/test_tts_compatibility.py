import pytest

from core.base.tts_compatibility import is_tongyi_wav_model, split_tts_text


def test_identifies_tongyi_qwen3_tts_flash() -> None:
    assert is_tongyi_wav_model("langgenius/tongyi/tongyi", "qwen3-tts-flash")
    assert not is_tongyi_wav_model("other/tongyi-compatible/provider", "other-model")


def test_split_tts_text_prefers_sentence_boundaries() -> None:
    chunks = split_tts_text("第一句话。第二句话比较长。第三句话。", max_length=12)

    assert chunks == ["第一句话。", "第二句话比较长。", "第三句话。"]
    assert all(len(chunk) <= 12 for chunk in chunks)


def test_split_tts_text_hard_splits_text_without_punctuation() -> None:
    chunks = split_tts_text("一二三四五六七八九十", max_length=4)

    assert chunks == ["一二三四", "五六七八", "九十"]


def test_split_tts_text_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        split_tts_text("text", max_length=0)
