"""Bounded extraction workflow; evidence validation and scoring are deterministic."""

import hashlib
import json
import os
import re
import time
from difflib import SequenceMatcher

import httpx
from . import config
from .models import EXTRACT_FIELDS, Extraction, Fact, SQLLead, Signal
from .storage import db
from .diagnostics import record

WEIGHTS = {"pain": 25, "timeline": 25, "budget": 20, "engagement": 20, "scale": 10}
LABELS = {
    "pain": "需求痛点",
    "timeline": "时间计划",
    "budget": "预算信息",
    "engagement": "推进动作",
    "scale": "使用规模",
}
FIELD_LABELS = dict(
    zip(
        EXTRACT_FIELDS,
        [
            "企业名称",
            "行业",
            "地区",
            "联系人",
            "职位",
            "手机号",
            "客户需求",
            "门店数",
            "设计师人数",
        ],
    )
)


class ModelError(Exception):
    def __init__(self, message, code="MODEL_ERROR"):
        super().__init__(message)
        self.code = code


def split_turns(text):
    lines = [s.strip() for s in text.replace("\r", "").split("\n") if s.strip()]
    turns = []
    for line in lines:
        match = re.match(
            r"^(?:\[[^\]]+\]\s*)?(销售|客户|客服|坐席|用户|顾客|sales|customer)\s*[:：]\s*(.*)",
            line,
            re.I,
        )
        speaker = "unknown"
        content = line
        if match:
            speaker = (
                "sales"
                if match[1].lower() in ("销售", "客服", "坐席", "sales")
                else "customer"
            )
            content = match[2]
        turns.append({"id": f"T{len(turns)+1}", "speaker": speaker, "text": content})
    return turns


def compact(text):
    return re.sub(r"\s+", "", text)


def normalize_extraction(payload):
    """Accept harmless JSON variations; never invent evidence or reinterpret scores."""
    if (
        not isinstance(payload, dict)
        or not {"fields", "signals", "refusal", "uncertainty"} <= payload.keys()
    ):
        raise ValueError("Extraction keys are incomplete")
    payload = dict(payload)
    for group in ("fields", "signals"):
        if not isinstance(payload[group], dict):
            raise ValueError("Extraction groups must be objects")
        payload[group] = dict(payload[group])
        for name, item in payload[group].items():
            if item is None:
                item = {}
            if not isinstance(item, dict):
                raise ValueError("Facts and signals must be objects")
            item = dict(item)
            for key in ("value", "quote", "turn_id", "explanation"):
                if key in item and item[key] is None:
                    item[key] = ""
            if group == "signals" and item.get("strength") in ("0", "1", "2"):
                item["strength"] = int(item["strength"])
            payload[group][name] = item
    if payload["refusal"] is None:
        payload["refusal"] = {}
    elif isinstance(payload["refusal"], dict):
        payload["refusal"] = {
            k: "" if v is None else v for k, v in payload["refusal"].items()
        }
    if payload["uncertainty"] is None:
        payload["uncertainty"] = []
    return Extraction.model_validate(payload)


def call_model(turns):
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise ModelError("未配置模型密钥，请配置后重试。", "MODEL_NOT_CONFIGURED")
    prompt = (config.ROOT / "prompts" / "extract.md").read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps({"turns": turns}, ensure_ascii=False)},
    ]
    base = config.BASE_URL
    endpoint = base + (
        "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
    )
    timeout = min(max(float(os.environ.get("LLM_TIMEOUT", "120")), 1), 240)
    max_tokens = 6000
    json_mode = True
    invalid_count = 0
    last_code = "MODEL_ERROR"
    started = time.monotonic()
    with httpx.Client(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 15)), follow_redirects=False
    ) as client:
        # Bound all recovery paths, including endpoint and provider capability fallback.
        for attempt in range(3):
            raw = ""
            try:
                params = {
                    "model": config.MODEL,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    params["response_format"] = {"type": "json_object"}
                response = client.post(
                    endpoint, headers={"Authorization": "Bearer " + key}, json=params
                )
                record(
                    "model",
                    "RESPONSE",
                    attempt=attempt + 1,
                    status=response.status_code,
                    max_tokens=max_tokens,
                )
                if (
                    response.status_code == 404
                    and not base.endswith("/v1")
                    and endpoint.endswith("/v1/chat/completions")
                ):
                    endpoint = base + "/chat/completions"
                    last_code = "MODEL_ENDPOINT"
                    continue
                if (
                    response.status_code in (400, 422)
                    and json_mode
                    and any(
                        word in response.text.lower()
                        for word in ("response_format", "json_object")
                    )
                ):
                    json_mode = False
                    last_code = "MODEL_JSON_MODE"
                    continue
                if response.status_code in (429, 500, 502, 503, 504):
                    last_code = "MODEL_BUSY"
                    if attempt < 2:
                        time.sleep(attempt + 1)
                        continue
                    raise ModelError(
                        "模型服务限流或暂时不可用，自动重试仍失败。转写文本已保留，请稍后再次分析。",
                        last_code,
                    )
                if response.status_code != 200:
                    if response.status_code in (401, 403):
                        raise ModelError(
                            "模型服务拒绝访问，请检查密钥、额度和模型权限。录音与转写文本不受影响。",
                            "MODEL_AUTH",
                        )
                    raise ModelError(
                        f"模型服务返回 HTTP {response.status_code}，请检查模型配置或输入长度后重试。",
                        "MODEL_HTTP",
                    )
                body = response.json()
                if not isinstance(body, dict) or not isinstance(
                    body.get("choices"), list
                ):
                    raise ValueError("Invalid model response envelope")
                choice = body["choices"][0]
                message = choice["message"]
                raw = message.get("content") or ""
                if not isinstance(raw, str):
                    raise ValueError("Model content must be text")
                if choice.get("finish_reason") == "length" or (
                    not raw.strip() and message.get("reasoning_content")
                ):
                    record(
                        "model",
                        "OUTPUT_TRUNCATED",
                        attempt=attempt + 1,
                        content_chars=len(raw) if isinstance(raw, str) else 0,
                    )
                    last_code = "MODEL_TRUNCATED"
                    if max_tokens == 6000 and attempt < 2:
                        max_tokens = 12000
                        # Regenerate from original evidence, never append incomplete assistant JSON.
                        continue
                    raise ModelError(
                        "模型输出仍被截断，未保存不完整结果。文本已保留，请重试或拆分超长通话。",
                        last_code,
                    )
                clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
                extraction = normalize_extraction(json.loads(clean))
                record(
                    "model",
                    "COMPLETED",
                    attempts=attempt + 1,
                    elapsed_seconds=round(time.monotonic() - started, 2),
                )
                return extraction, {
                    "provider_model": body.get("model", config.MODEL),
                    "usage": body.get("usage", {}),
                    "attempts": attempt + 1,
                }
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                invalid_count += 1
                record(
                    "model",
                    "INVALID_STRUCTURE",
                    attempt=attempt + 1,
                    exception_type=type(exc).__name__,
                    content_chars=len(raw) if isinstance(raw, str) else 0,
                )
                if invalid_count < 2 and attempt < 2:
                    messages = messages[:2] + [
                        {
                            "role": "user",
                            "content": "上次输出结构无效。请重新依据通话输出完整JSON：fields和signals为对象，refusal为对象，uncertainty为字符串数组。未知字段使用空字符串；strength只能是整数0、1、2；quote必须逐字引用对应turn_id。不要输出额外字段、思考过程或Markdown。",
                        }
                    ]
                    last_code = "MODEL_STRUCTURE"
                    continue
                raise ModelError(
                    "模型未返回有效结构，自动修复仍失败。转写文本已保留，请再次分析。",
                    "MODEL_STRUCTURE",
                ) from exc
            except httpx.HTTPError as exc:
                last_code = (
                    "MODEL_TIMEOUT"
                    if isinstance(exc, httpx.TimeoutException)
                    else "MODEL_CONNECTION"
                )
                record(
                    "model",
                    last_code,
                    attempt=attempt + 1,
                    exception_type=type(exc).__name__,
                )
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise ModelError(
                    "模型连接失败或超时，自动重试仍失败。转写文本已保留，无需重新上传录音。",
                    last_code,
                ) from exc
    raise ModelError(
        "模型接口未能完成请求，请检查接口配置后重试。转写文本已保留。", last_code
    )


def baseline(turns):
    """Explicitly labelled demo baseline. Not a silent substitute for the configured LLM."""
    ex = Extraction()
    patterns = {
        "company_name": r"(?:公司(?:全称)?(?:叫|是)|我们叫|品牌叫|叫[“\"「]?)([^，。！？；”\"」]{2,30})",
        "industry": r"(全屋定制|高端定制|家居定制|室内设计|装修|装饰|家具|家装|橱柜)",
        "area": r"(北京|上海|杭州|广州|深圳|成都|武汉|南京|苏州|宁波|重庆|天津|西安|合肥|郑州|长沙)",
        "phone": r"(1[3-9][0-9xX*]{9})",
        "mendian": r"([约大概左右\d一二两三四五六七八九十百零到至\-]+\s*家)(?:门店|店)",
        "shejishi": r"(?:设计部|设计师)(?:大概|有|人数|是|大约|约|一共|就|\s)*([\d一二两三四五六七八九十百零到至\-]+\s*(?:个|位|人)(?:人)?)",
    }
    for turn in turns:
        text = turn["text"]
        if turn["speaker"] == "sales":
            match = re.search(r"([\u4e00-\u9fff]{1,2}(?:总|经理|先生|女士))", text)
            if match and "contact_name" not in ex.fields:
                value = match[1]
                prefix = re.match(r"([\u4e00-\u9fff]{2})(?:总|经理|先生|女士)$", value)
                if prefix and prefix[1][0] in "是好问叫您你":
                    value = value[1:]
                ex.fields["contact_name"] = Fact(
                    value=value, quote=match[0], turn_id=turn["id"]
                )
            continue
        for name, pattern in patterns.items():
            matches = list(re.finditer(pattern, text))
            if matches:
                match = matches[-1]
                ex.fields[name] = Fact(
                    value=match[1].strip(), quote=match[0], turn_id=turn["id"]
                )
        alt = re.search(
            r"([\d一二两三四五六七八九十百零]+)\s*(?:个|位|名)?设计师", text
        )
        if alt:
            ex.fields["shejishi"] = Fact(
                value=alt[1] + "人", quote=alt[0], turn_id=turn["id"]
            )
        rules = {
            "pain": (
                r"出图慢|出图很慢|对接.*出错|效率低|经常返工",
                r"想了解|想改善|想解决|了解一下",
            ),
            "timeline": (
                r"下个月|这周|本周|下周|月底|本月|尽快|马上",
                r"以后|过段时间|有计划",
            ),
            "budget": (
                r"预算.*(?:万|千|元)|(?:万|千|元).*能接受|一年几万",
                r"可以付费|考虑付费",
            ),
            "engagement": (
                r"安排.*演示|想.*试用|发.*报价|下周.*演示|下个月.*试一下|约.*演示",
                r"加.*微信|加这个手机号|发.*资料|发.*方案",
            ),
            "scale": (
                r"(?:[2-9]|1\d|[二两三四五六七八九十]).*(?:设计师|个人|门店)|设计部.*(?:[2-9]|1\d|[二两三四五六七八九十])",
                r"一个人|我自己用",
            ),
        }
        for name, (strong, weak) in rules.items():
            strength = (
                2 if re.search(strong, text) else 1 if re.search(weak, text) else 0
            )
            if strength and strength >= ex.signals.get(name, Signal()).strength:
                ex.signals[name] = Signal(
                    strength=strength,
                    quote=text,
                    turn_id=turn["id"],
                    explanation="本地规则命中，需人工核实",
                )
        if re.search(r"不需要|别再打|不要联系|不考虑采购|不买了", text):
            ex.refusal = Fact(value="客户明确拒绝", quote=text, turn_id=turn["id"])
    pain = ex.signals.get("pain")
    if pain:
        ex.fields["demand_summary"] = Fact(
            value=pain.quote, quote=pain.quote, turn_id=pain.turn_id
        )
    ex.uncertainty.append("本地基线仅用于演示与对照，未经模型语义复核")
    return ex, {"provider_model": "local-baseline", "usage": {}, "attempts": 0}


def validate_evidence(ex, turns):
    by_id = {t["id"]: t for t in turns}
    warnings = list(ex.uncertainty)
    evidence = {}
    fields = {}

    def grounded(item, allow_sales=False):
        turn = by_id.get(item.turn_id)
        if (
            not turn
            or not item.quote.strip()
            or compact(item.quote) not in compact(turn["text"])
        ):
            return False
        return allow_sales or turn["speaker"] != "sales"

    for name in EXTRACT_FIELDS:
        fact = ex.fields.get(name, Fact())
        if name == "area" and fact.value:
            fact = fact.model_copy(
                update={
                    "value": re.sub(
                        r"(?:那边|这边|这儿|那儿|附近|一带|这块|那块)$", "", fact.value
                    ).strip()
                }
            )
        literal_field = name in (
            "company_name",
            "phone",
            "contact_title",
            "contact_name",
        )
        literal_supported = not literal_field or compact(fact.value) in compact(
            fact.quote
        )
        if fact.value and literal_supported and grounded(fact, name == "contact_name"):
            fields[name] = fact.value
            evidence[name] = fact.model_dump()
        else:
            fields[name] = ""
            if fact.value:
                warnings.append(f"{name}缺少有效原文证据，已清空")
    signals = {}
    for name in WEIGHTS:
        signal = ex.signals.get(name, Signal())
        if signal.strength and not grounded(signal):
            warnings.append(f"{LABELS[name]}证据无效或来自销售，未计分")
            signal = Signal()
        if name == "budget" and signal.strength and budget_is_negated(signal.quote):
            warnings.append("预算证据含否定，未计积极分")
            signal = Signal()
        signals[name] = signal.model_dump()
    refusal = ex.refusal if ex.refusal.value and grounded(ex.refusal) else Fact()
    if any(t["speaker"] == "unknown" for t in turns):
        warnings.append("部分发言未区分客户与销售，请核实说话人")
    return fields, evidence, signals, refusal, list(dict.fromkeys(warnings))


def budget_is_negated(quote):
    """A budget cap is different from no funds; later approval supersedes old lack."""
    text = re.sub(r"没(?:有)?预算(?:限制|上限)", "预算充足", quote)
    negatives = list(
        re.finditer(
            r"没(?:有)?预算|预算(?:还|尚)?(?:没(?:有)?批|未批|尚未批)|不考虑付费",
            text,
        )
    )
    if not negatives:
        return False
    # Only a stated approval changes an earlier lack of funds, not a future hope.
    later = text[negatives[-1].end() :]
    return not bool(
        re.search(
            r"(?:现在|目前|现已|已经).{0,8}(?:批了|已批|批准|通过)|(?:预算|经费)(?:已经|现已|已)(?:批准|通过|到位|落实)",
            later,
        )
    )


def score_intent(signals, refusal):
    card = []
    for name, weight in WEIGHTS.items():
        signal = signals[name]
        points = weight * signal["strength"] / 2
        card.append(
            {
                "key": name,
                "label": LABELS[name],
                "weight": weight,
                "points": points,
                **signal,
            }
        )
    total = sum(row["points"] for row in card)
    gate = signals["engagement"]["strength"] >= 1 and (
        signals["timeline"]["strength"] == 2 or signals["budget"]["strength"] == 2
    )
    level = "high" if total >= 70 and gate else "medium" if total >= 30 else "low"
    reasons = [
        f'{row["label"]}：{row["explanation"] or row["quote"]}'
        for row in card
        if row["points"]
    ]
    if refusal.value:
        level = "low"
        reasons = [f"当前明确拒绝优先：{refusal.quote}"] + reasons
    if not reasons:
        reasons = ["未取得足够积极意向证据，暂列低意向；这不等同于客户明确拒绝。"]
    if total >= 70 and not gate and not refusal.value:
        reasons.append("尚未满足高意向的明确预算/近期计划及推进条件")
    return {
        "level": level,
        "score": total,
        "card": card,
        "reason": "；".join(reasons),
        "high_gate_met": gate,
        "refusal": refusal.model_dump(),
        "version": "1.0",
    }


def same_context(stored, actual):
    # Partial strings (e.g. 杭州 vs 杭州湾) cannot establish the same business context.
    def normalize(value):
        value = compact(value).lower()
        return re.sub(r"(?:市|地区)$", "", value)

    return bool(stored and actual and normalize(stored) == normalize(actual))


def resolve_company(fields):
    raw = fields["company_name"]
    result = {
        "raw_name": raw,
        "display_name": raw,
        "status": "missing",
        "support": 0.15,
        "candidates": [],
        "note": "客户企业名称未确认",
    }
    if not raw:
        return result
    with db() as con:
        rows = con.execute("SELECT * FROM aliases WHERE alias=?", (raw,)).fetchall()
    verified = [
        dict(r)
        for r in rows
        if same_context(r["area"], fields["area"])
        and same_context(r["industry"], fields["industry"])
    ]
    unique = {r["company_name"] for r in verified}
    if len(unique) == 1:
        result.update(
            display_name=next(iter(unique)),
            status="verified",
            support=0.95,
            candidates=verified,
            note="命中人工核验词库，地区与行业匹配",
        )
        return result
    if len(unique) > 1:
        result.update(
            status="ambiguous",
            support=0.35,
            candidates=verified,
            note="同一上下文存在多个已确认主体，需重新消歧",
        )
        return result
    if re.search(r"(?:有限责任公司|有限公司|股份公司|工作室|个体工商户)$", raw):
        result.update(
            status="self_reported",
            support=0.72,
            note="客户自报完整名称，尚未独立核验工商主体",
        )
        return result
    brands = json.loads(
        (config.ROOT / "data" / "brands.json").read_text(encoding="utf-8")
    )
    for brand in brands:
        similarity = max(
            (SequenceMatcher(None, alias, raw).ratio() for alias in brand["aliases"]),
            default=0,
        )
        if similarity >= 0.7:
            result["candidates"].append(
                {
                    "company_name": brand["name"],
                    "kind": "brand",
                    "similarity": round(similarity, 2),
                    "source": brand["source"],
                }
            )
    result["candidates"].sort(key=lambda r: r.get("similarity", 0), reverse=True)
    if result["candidates"]:
        top = result["candidates"][0]
        result.update(
            status="brand_only",
            support=0.55,
            note="找到品牌候选；品牌方、经销商与加盟门店不能直接视为同一工商主体",
        )
        # Even an exact brand alias is only a brand normalization, never a legal name.
        if top["similarity"] == 1:
            result["display_name"] = top["company_name"]
        references = json.loads(
            (config.ROOT / "data" / "company_references.json").read_text(
                encoding="utf-8"
            )
        )
        for reference in references:
            if reference["brand"] == top["company_name"] and (
                not reference["area"] or same_context(reference["area"], fields["area"])
            ):
                result["candidates"].append(reference)
    else:
        result.update(
            status="unresolved",
            support=0.35,
            note="暂无可靠企业候选，建议补问门店全称与经营地址",
        )
    return result


def analyze(text, mode="llm", call_time=""):
    start = time.monotonic()
    turns = split_turns(text)
    ex, provider = call_model(turns) if mode == "llm" else baseline(turns)
    fields, evidence, signals, refusal, warnings = validate_evidence(ex, turns)
    company = resolve_company(fields)
    intent = score_intent(signals, refusal)
    reasons = []
    if company["status"] != "verified":
        reasons.append(company["note"])
    for warning in warnings:
        for key, label in FIELD_LABELS.items():
            warning = warning.replace(key, label)
        reasons.append(warning)
    if 25 <= intent["score"] <= 35 or 65 <= intent["score"] <= 75:
        reasons.append("意向评分处于分级边界附近")
    if not fields["phone"]:
        reasons.append("缺少客户联系方式")
    if not fields["demand_summary"] and not refusal.value:
        reasons.append("客户需求尚未明确")
    if mode == "baseline":
        reasons.append("本地基线结果需人工复核")
    evidence_support = 0.95 if evidence and not warnings else 0.65 if evidence else 0.2
    intent_support = (
        0.9
        if refusal.value or len([s for s in signals.values() if s["strength"]]) >= 3
        else 0.55
    )
    confidence = round(
        0.4 * evidence_support + 0.3 * company["support"] + 0.3 * intent_support, 2
    )
    if confidence < 0.8:
        reasons.append("综合证据支持度低于审核阈值0.80")
    next_action = "补充确认企业主体、需求与采购计划"
    if refusal.value:
        next_action = "尊重客户拒绝；如要求停止联系，登记停止联系，不继续营销跟进"
    elif intent["level"] == "high":
        next_action = "按客户表达的时间确认演示或试用安排，并核实签约主体与决策人"
    elif intent["level"] == "medium":
        next_action = "围绕已确认痛点发送针对性方案，补问预算与试用时间"
    fields["company_name"] = company["display_name"]
    lead = SQLLead(
        **fields,
        call_time=call_time,
        intent_level=intent["level"],
        intent_reason=intent["reason"],
        next_action=next_action,
        confidence_score=confidence,
        need_human_review=bool(reasons),
    )
    analysis = {
        "turns": turns,
        "evidence": evidence,
        "company": company,
        "intent": intent,
        "review_reasons": list(dict.fromkeys(reasons)),
        "mode": mode,
        **provider,
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "prompt_version": config.PROMPT_VERSION,
        "input_hash": hashlib.sha256(text.encode()).hexdigest(),
        "confidence_note": "启发式证据支持度，尚未用独立样本校准为正确概率",
        "workflow": [
            "发言整理",
            "事实与信号抽取",
            "原文证据校验",
            "企业候选消歧",
            "评分卡判级",
            "审核分流",
        ],
    }
    return lead.model_dump(), analysis


def search_company(name, area, industry):
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise ModelError(
            "未配置外部搜索。可先依据原文审核，或配置TAVILY_API_KEY后检索企业候选。"
        )
    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": f"{name[:100]} {area[:60]} {industry[:60]} 企业 门店 工商主体",
                "max_results": 5,
            },
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise ValueError("Invalid search response")
        return [
            {
                "title": r.get("title") if isinstance(r.get("title"), str) else "",
                "url": r["url"],
                "content": (
                    r["content"][:1800] if isinstance(r.get("content"), str) else ""
                ),
            }
            for r in body["results"]
            if isinstance(r, dict)
            and isinstance(r.get("url"), str)
            and r["url"].startswith("https://")
        ]
    except (httpx.HTTPError, ValueError) as exc:
        raise ModelError("企业候选检索失败，请稍后重试。") from exc
