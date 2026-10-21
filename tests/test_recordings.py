from app.recordings import transcript_quality


def test_sparse_transcription_is_flagged_without_asserting_invalid_audio():
    result = transcript_quality(
        {"duration": 300, "segments": [{"start": 0, "end": 9, "avg_logprob": -0.2}]}
    )
    assert result["voiced_fraction"] == 0.03
    assert any("回听" in flag for flag in result["quality_flags"])


def test_normal_coverage_has_no_sparse_warning():
    result = transcript_quality(
        {"duration": 100, "segments": [{"start": 0, "end": 80, "avg_logprob": -0.3}]}
    )
    assert result["voiced_fraction"] == 0.8
    assert result["quality_flags"] == []


def test_empty_transcript_is_not_division_by_zero():
    result = transcript_quality({"duration": 0, "segments": []})
    assert result["voiced_fraction"] == 0


def test_long_timestamp_cannot_hide_an_almost_empty_legacy_transcript():
    result = transcript_quality(
        {
            "duration": 360,
            "segments": [{"start": 7, "end": 86, "text": "乱码", "avg_logprob": -0.2}],
        }
    )
    assert any("不匹配" in flag for flag in result["quality_flags"])


def test_overlapping_and_out_of_range_segments_do_not_inflate_coverage():
    result = transcript_quality(
        {
            "duration": 100,
            "segments": [
                {"start": -10, "end": 10},
                {"start": 5, "end": 20},
                {"start": 90, "end": 150},
            ],
        }
    )
    assert result["voiced_fraction"] == 0.3


def test_corrupt_cached_transcript_can_be_retranscribed(tmp_path, monkeypatch):
    from app import config, recordings

    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "test.json").write_text("{broken", encoding="utf-8")
    result = recordings.cached_transcript("test")
    assert result["text"] == "" and result["quality_flags"]


def test_invalid_date_in_recording_name_does_not_break_material_list(
    tmp_path, monkeypatch
):
    from app import config, recordings

    (tmp_path / "[1]-20261301120000-synthetic.mp3").write_bytes(b"ID3")
    recordings.index.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(config, "RECORDINGS", tmp_path)
            items = list(recordings.index().values())
            assert len(items) == 1 and items[0]["call_time"] == ""
    finally:
        recordings.index.cache_clear()
