import json
import pytest
from app import agent, config
from app.models import Extraction, Fact, SQLLead, Signal
from app.storage import init, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    init()


def signals(**strengths):
    return {
        k: {
            "strength": strengths.get(k, 0),
            "quote": "原文",
            "turn_id": "T1",
            "explanation": "证据",
        }
        for k in agent.WEIGHTS
    }


def test_exact_fifteen_field_contract():
    assert len(SQLLead.model_fields) == 15
    assert SQLLead().mendian == ""
    with pytest.raises(ValueError):
        SQLLead(intent_level="unknown")
    with pytest.raises(ValueError):
        SQLLead(confidence_score=1.1)
    with pytest.raises(ValueError):
        SQLLead(extra_field="no")


def test_turn_roles_and_timestamps():
    turns = agent.split_turns(
        "[1.2s] 销售：预算一年三万。\n客户：先看看。\n无法分离的话"
    )
    assert [t["speaker"] for t in turns] == ["sales", "customer", "unknown"]
    assert turns[0]["text"] == "预算一年三万。"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("请问是张总吗？", "张总"),
        ("你好李经理。", "李经理"),
        ("欧阳总，您好。", "欧阳总"),
    ],
)
def test_salutation_does_not_include_question_prefix(text, expected):
    extraction, _ = agent.baseline(agent.split_turns("销售：" + text))
    assert extraction.fields["contact_name"].value == expected


def test_sales_signals_do_not_inflate_intent():
    turns = agent.split_turns("销售：下周上线，预算三万。\n客户：先看看。")
    ex = Extraction(
        signals={"budget": Signal(strength=2, quote="预算三万", turn_id="T1")}
    )
    _, _, sigs, _, warnings = agent.validate_evidence(ex, turns)
    assert sigs["budget"]["strength"] == 0
    assert warnings


def test_nonexistent_evidence_is_discarded():
    turns = agent.split_turns("客户：我们在杭州。")
    ex = Extraction(
        fields={
            "phone": Fact(value="13800000000", quote="电话13800000000", turn_id="T1")
        }
    )
    fields, evidence, _, _, warnings = agent.validate_evidence(ex, turns)
    assert fields["phone"] == "" and "phone" not in evidence and warnings


def test_quote_must_belong_to_declared_turn():
    turns = agent.split_turns("客户：我们在杭州。\n客户：十个设计师。")
    ex = Extraction(
        fields={"area": Fact(value="杭州", quote="我们在杭州", turn_id="T2")}
    )
    fields, *_ = agent.validate_evidence(ex, turns)
    assert fields["area"] == ""


def test_company_phone_and_title_cannot_be_expanded_from_a_valid_quote():
    turns = agent.split_turns("客户：我们叫木里木外，大家叫我张总。")
    ex = Extraction(
        fields={
            "company_name": Fact(
                value="木里木外家居有限公司", quote="我们叫木里木外", turn_id="T1"
            ),
            "contact_title": Fact(value="总经理", quote="大家叫我张总", turn_id="T1"),
        }
    )
    fields, *_ = agent.validate_evidence(ex, turns)
    assert fields["company_name"] == fields["contact_title"] == ""


def test_unknown_speaker_always_warns():
    _, _, _, _, warnings = agent.validate_evidence(
        Extraction(), agent.split_turns("我们想试用")
    )
    assert any("说话人" in w or "销售" in w for w in warnings)


def test_verified_company_context_cannot_use_partial_names():
    assert agent.same_context("杭州市", "杭州")
    assert not agent.same_context("杭州", "杭州湾")
    assert not agent.same_context("家居", "办公家居")


def test_budget_negation_cannot_score():
    turns = agent.split_turns("客户：我们没有预算。")
    ex = Extraction(
        signals={"budget": Signal(strength=2, quote="我们没有预算", turn_id="T1")}
    )
    _, _, sigs, _, _ = agent.validate_evidence(ex, turns)
    assert sigs["budget"]["strength"] == 0


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("没有预算限制，五万以内都能接受", 2),
        ("没有预算上限，五万元没问题", 2),
        ("原来没有预算，现在批了五万元", 2),
        ("我们没有预算，先发资料", 0),
        ("预算未批，暂时不能采购", 0),
        ("之前没有预算，希望下个月能批五万", 0),
        ("预算已经批准，但现在没有预算了", 0),
    ],
)
def test_budget_guard_distinguishes_limits_and_current_approval(quote, expected):
    ex = Extraction(signals={"budget": Signal(strength=2, quote=quote, turn_id="T1")})
    _, _, sigs, _, _ = agent.validate_evidence(ex, agent.split_turns("客户：" + quote))
    assert sigs["budget"]["strength"] == expected


def test_spoken_location_suffix_is_normalized_without_losing_quote():
    turns = agent.split_turns("客户：我们在杭州那边。")
    ex = Extraction(
        fields={"area": Fact(value="杭州那边", quote="我们在杭州那边", turn_id="T1")}
    )
    fields, evidence, *_ = agent.validate_evidence(ex, turns)
    assert fields["area"] == "杭州"
    assert evidence["area"]["quote"] == "我们在杭州那边"


def test_high_intent_requires_gate():
    decision = agent.score_intent(
        signals(pain=2, budget=2, scale=2, engagement=2), Fact()
    )
    assert decision["score"] == 75 and decision["level"] == "high"
    decision = agent.score_intent(
        signals(pain=2, timeline=2, budget=2, scale=2), Fact()
    )
    assert decision["score"] == 80 and decision["level"] == "medium"


def test_refusal_overrides_historical_positive_signals():
    decision = agent.score_intent(
        signals(**{k: 2 for k in agent.WEIGHTS}), Fact(value="拒绝", quote="不需要了")
    )
    assert decision["level"] == "low" and decision["score"] == 100
    assert "拒绝" in decision["reason"]


def test_no_evidence_is_not_asserted_refusal():
    decision = agent.score_intent(signals(), Fact())
    assert decision["level"] == "low"
    assert "不等同于" in decision["reason"]


def test_brand_never_expands_into_legal_company():
    decision = agent.resolve_company(
        {"company_name": "木里木外", "area": "杭州", "industry": "全屋定制"}
    )
    assert decision["status"] == "brand_only"
    assert decision["display_name"] == "木里木外"
    assert "有限公司" not in decision["display_name"]


def test_self_reported_full_name_remains_unverified():
    decision = agent.resolve_company(
        {"company_name": "测试家居有限公司", "area": "杭州", "industry": "全屋定制"}
    )
    assert decision["status"] == "self_reported"


def test_official_references_help_review_without_claiming_customer_identity():
    decision = agent.resolve_company(
        {"company_name": "木里木歪", "area": "杭州", "industry": "全屋定制"}
    )
    assert decision["display_name"] == "木里木外"
    assert decision["status"] == "brand_only"
    references = [
        c for c in decision["candidates"] if c.get("kind") == "official_reference"
    ]
    assert references and references[0]["url"].startswith("https://www.muli.group/")
    assert any(c.get("kind") == "store_reference" for c in decision["candidates"])
    other_city = agent.resolve_company(
        {"company_name": "木里木外", "area": "北京", "industry": "全屋定制"}
    )
    assert not any(c.get("kind") == "store_reference" for c in other_city["candidates"])


def test_aliases_are_scoped_and_ambiguity_is_retained():
    with db() as con:
        con.execute(
            "INSERT INTO aliases(alias,company_name,area,industry,source,reviewer,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                "测试品牌",
                "杭州测试有限公司",
                "杭州",
                "全屋定制",
                "核验",
                "审核员",
                "now",
            ),
        )
    assert (
        agent.resolve_company(
            {"company_name": "测试品牌", "area": "杭州", "industry": "全屋定制"}
        )["status"]
        == "verified"
    )
    assert (
        agent.resolve_company(
            {"company_name": "测试品牌", "area": "苏州", "industry": "全屋定制"}
        )["status"]
        != "verified"
    )
    assert (
        agent.resolve_company(
            {"company_name": "测试品牌", "area": "", "industry": "全屋定制"}
        )["status"]
        != "verified"
    )
    with db() as con:
        con.execute(
            "INSERT INTO aliases(alias,company_name,area,industry,source,reviewer,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                "测试品牌",
                "杭州另一测试有限公司",
                "杭州",
                "全屋定制",
                "核验",
                "审核员",
                "now",
            ),
        )
    assert (
        agent.resolve_company(
            {"company_name": "测试品牌", "area": "杭州", "industry": "全屋定制"}
        )["status"]
        == "ambiguous"
    )


def test_assignment_baseline_flow_retains_missing_values():
    text = json.loads(
        (config.ROOT / "data" / "examples.json").read_text(encoding="utf-8")
    )[0]["text"]
    result, analysis = agent.analyze(text, "baseline")
    assert result["need_human_review"]
    assert result["mendian"] == ""
    assert result["contact_title"] == ""
    assert analysis["mode"] == "baseline"


def test_model_failure_never_silently_falls_back(monkeypatch):
    def failed(*a):
        raise agent.ModelError("测试失败")

    monkeypatch.setattr(agent, "call_model", failed)
    with pytest.raises(agent.ModelError):
        agent.analyze("客户：你好", "llm")
