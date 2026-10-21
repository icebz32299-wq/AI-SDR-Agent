import json
from types import SimpleNamespace

from app.asr_progress import collect_transcript, repetition_error


def test_entire_generator_is_consumed_and_tail_preserved(tmp_path):
    seen = []

    def segments():
        for i in range(120):
            seen.append(i)
            yield SimpleNamespace(
                start=i * 5,
                end=(i + 1) * 5,
                text=f"第{i}段：企业甲，预算50000元。",
                avg_logprob=-0.2,
            )

    progress_path = tmp_path / "progress.json"
    result = collect_transcript(
        segments(),
        SimpleNamespace(duration=600.0, language="zh"),
        "test",
        progress_path,
    )
    assert len(seen) == len(result["segments"]) == 120
    assert result["text"].endswith("第119段：企业甲，预算50000元。")
    assert result["complete"] is True and result["processed_seconds"] == 600
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["percent"] == 99 and progress["processed_seconds"] == 600
    assert "\ufffd" not in result["text"]


def test_repeated_hallucination_is_not_a_valid_transcript():
    assert repetition_error([{"text": "您好。"}] * 100)
    assert not repetition_error([{"text": "好的"}, {"text": "谢谢"}] * 3)


def test_asr_retries_repetition_and_keeps_complete_recovered_text(tmp_path):
    from scripts.transcribe import transcribe_with_recovery

    class Model:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, **options):
            self.calls.append(options)
            if len(self.calls) == 1:
                segments = [
                    SimpleNamespace(
                        start=i, end=i + 1, text="重复幻觉", avg_logprob=-1.5
                    )
                    for i in range(30)
                ]
            else:
                segments = [
                    SimpleNamespace(
                        start=0,
                        end=70,
                        text="客户确认设计师十五人，出图慢。",
                        avg_logprob=-0.2,
                    ),
                    SimpleNamespace(
                        start=90,
                        end=120,
                        text="最后确认预算三万元，下月试用。",
                        avg_logprob=-0.2,
                    ),
                ]
            return iter(segments), SimpleNamespace(duration=120.0, language="zh")

    model = Model()
    result = transcribe_with_recovery(
        model, None, "synthetic", tmp_path / "progress.json"
    )
    assert result["complete"] and result["processed_seconds"] == 120
    assert result["asr_attempts"] == result["selected_attempt"] == 2
    assert result["text"].endswith("最后确认预算三万元，下月试用。")
    assert all(not c["condition_on_previous_text"] for c in model.calls)
    assert model.calls[1]["vad_parameters"]["threshold"] < 0.5


def test_asr_does_not_replace_good_first_result_with_worse_retry():
    from scripts.transcribe import transcribe_with_recovery

    class Model:
        calls = 0

        def transcribe(self, audio, **options):
            self.calls += 1
            rows = (
                [
                    SimpleNamespace(
                        start=0, end=8, text="客户：不用了，谢谢。", avg_logprob=-0.2
                    )
                ]
                if self.calls == 1
                else []
            )
            return iter(rows), SimpleNamespace(duration=180.0, language="zh")

    result = transcribe_with_recovery(Model(), None, "synthetic")
    assert result["selected_attempt"] == 1 and result["asr_attempts"] == 2
    assert "不用了" in result["text"]
