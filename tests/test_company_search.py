import httpx
import pytest

from app import agent


def response(body):
    return httpx.Response(
        200, json=body, request=httpx.Request("POST", "https://api.tavily.com/search")
    )


def test_search_sends_only_company_context_and_tolerates_bad_result_rows(monkeypatch):
    captured = {}
    monkeypatch.setenv("TAVILY_API_KEY", "synthetic-search-key")

    def post(url, **options):
        captured.update(options["json"])
        return response(
            {
                "results": [
                    None,
                    {"url": None},
                    {"url": "javascript:alert(1)"},
                    {
                        "title": None,
                        "url": "https://example.test/company",
                        "content": None,
                    },
                ]
            }
        )

    monkeypatch.setattr(agent.httpx, "post", post)
    result = agent.search_company("合成企业", "杭州", "全屋定制")
    assert captured["query"] == "合成企业 杭州 全屋定制 企业 门店 工商主体"
    assert set(captured) == {"api_key", "query", "max_results"}
    assert result == [
        {"title": "", "url": "https://example.test/company", "content": ""}
    ]


@pytest.mark.parametrize("body", [None, [], {"results": None}])
def test_invalid_search_envelope_is_an_actionable_error(monkeypatch, body):
    monkeypatch.setenv("TAVILY_API_KEY", "synthetic-search-key")
    monkeypatch.setattr(agent.httpx, "post", lambda *args, **kw: response(body))
    with pytest.raises(agent.ModelError, match="检索失败"):
        agent.search_company("合成企业", "杭州", "全屋定制")


def test_missing_search_key_explains_manual_verification(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(agent.ModelError, match="未配置外部搜索"):
        agent.search_company("合成企业", "杭州", "全屋定制")
