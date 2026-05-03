from types import SimpleNamespace

import pytest
import requests
from langchain.tools import ToolRuntime

from agents.data_engineer import tools as data_engineer_tools
from mcp_clients.sec_edgar_client import SECEdgarClient, SECEdgarError


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = responses or {}
        self.error = error
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        for key, response in self.responses.items():
            if key in url:
                return response
        raise AssertionError(f"Unexpected URL: {url}")


def _runtime(job_id="job-sec"):
    return ToolRuntime(
        state={},
        context=SimpleNamespace(job_id=job_id),
        config={},
        stream_writer=lambda _: None,
        tool_call_id=None,
        store=None,
    )


def _companyfacts_payload():
    return {
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 391035000000,
                            },
                            {
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2023-09-30",
                                "filed": "2023-11-03",
                                "val": 383285000000,
                            },
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2024-06-30",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 94930000000,
                            },
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2018,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2017-10-01",
                                "end": "2018-09-29",
                                "filed": "2018-11-05",
                                "val": 265595000000,
                            }
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "filed": "2024-11-01",
                                "val": 96995000000,
                            },
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 93736000000,
                            },
                        ]
                    }
                },
                "GrossProfit": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 180683000000,
                            }
                        ]
                    }
                },
                "OperatingIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 123216000000,
                            }
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 118254000000,
                            }
                        ]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 9447000000,
                            }
                        ]
                    }
                },
                "PaymentsToAcquireProductiveAssets": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2022-10-01",
                                "end": "2023-09-30",
                                "filed": "2023-11-03",
                                "val": 10959000000,
                            }
                        ]
                    }
                },
                "ResearchAndDevelopmentExpense": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 31370000000,
                            }
                        ]
                    }
                },
                "SellingGeneralAndAdministrativeExpense": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 26097000000,
                            }
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 6.08,
                            }
                        ]
                    }
                },
                "CashAndCashEquivalentsAtCarryingValue": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 29943000000,
                            }
                        ]
                    }
                },
                "MarketableSecuritiesCurrent": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 35228000000,
                            }
                        ]
                    }
                },
                "LongTermDebtNoncurrent": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 85750000000,
                            }
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 56950000000,
                            }
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 364980000000,
                            }
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 308030000000,
                            }
                        ]
                    }
                },
                "CommonStocksSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": 15116786000,
                            }
                        ]
                    }
                },
            }
        },
    }


def _submissions_payload():
    return {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["8-K", "10-K", "10-Q"],
                "accessionNumber": ["x", "0000320193-24-000123", "0000320193-24-000081"],
                "filingDate": ["2025-01-01", "2024-11-01", "2024-08-02"],
                "reportDate": ["2025-01-01", "2024-09-28", "2024-06-29"],
                "primaryDocument": ["x.htm", "aapl-20240928.htm", "aapl-20240629.htm"],
            }
        },
    }


def test_sec_client_fetches_company_facts_and_sends_user_agent():
    session = FakeSession(
        {
            "company_tickers": FakeResponse({"0": {"ticker": "AAPL", "cik_str": 320193}}),
            "companyfacts": FakeResponse(_companyfacts_payload()),
            "submissions": FakeResponse(_submissions_payload()),
        }
    )

    result = SECEdgarClient(
        session=session,
        user_agent="DeepResearchAgent tests contact@example.com",
    ).get_company_facts("AAPL", periods=2)

    assert result["status"] == "success"
    assert result["provider"] == "SEC EDGAR"
    assert result["ticker"] == "AAPL"
    assert result["cik"] == "0000320193"
    assert result["metadata"]["requires_api_key"] is False
    assert result["fundamentals"][0]["fiscal_year"] == 2024
    assert result["fundamentals"][0]["revenue"] == 391035000000
    assert result["fundamentals"][0]["revenue_concept"] == (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert result["fundamentals"][0]["net_income"] == 93736000000
    assert result["fundamentals"][0]["net_income_end"] == "2024-09-28"
    assert result["fundamentals"][0]["gross_profit"] == 180683000000
    assert result["fundamentals"][0]["operating_income"] == 123216000000
    assert result["fundamentals"][0]["operating_cash_flow"] == 118254000000
    assert result["fundamentals"][0]["capital_expenditures"] == 9447000000
    assert result["fundamentals"][0]["research_and_development"] == 31370000000
    assert result["fundamentals"][0]["selling_general_and_admin"] == 26097000000
    assert result["fundamentals"][0]["diluted_eps"] == 6.08
    assert result["fundamentals"][0]["cash_and_equivalents"] == 29943000000
    assert result["fundamentals"][0]["marketable_securities_current"] == 35228000000
    assert result["fundamentals"][0]["long_term_debt"] == 85750000000
    assert result["fundamentals"][0]["stockholders_equity"] == 56950000000
    assert result["fundamentals"][0]["assets"] == 364980000000
    assert result["fundamentals"][0]["liabilities"] == 308030000000
    assert result["fundamentals"][0]["shares"] == 15116786000
    assert result["fundamentals"][1]["fiscal_year"] == 2023
    assert result["fundamentals"][1]["revenue"] == 383285000000
    assert result["fundamentals"][1]["capital_expenditures"] == 10959000000
    assert result["fundamentals"][1]["capital_expenditures_concept"] == (
        "PaymentsToAcquireProductiveAssets"
    )
    assert result["filings"][0]["form"] == "10-K"
    assert all(
        call["headers"]["User-Agent"] == "DeepResearchAgent tests contact@example.com"
        for call in session.calls
    )


def test_sec_client_rejects_malformed_ticker_without_network_call():
    session = FakeSession()

    with pytest.raises(SECEdgarError) as exc_info:
        SECEdgarClient(session=session).get_company_facts("AAPL!")

    assert "Malformed ticker/CIK" in str(exc_info.value)
    assert session.calls == []


def test_sec_client_returns_disabled_payload_without_network_call():
    session = FakeSession()

    result = SECEdgarClient(session=session, enabled=False).get_company_facts("AAPL")

    assert result["status"] == "disabled"
    assert result["provider"] == "SEC EDGAR"
    assert session.calls == []


def test_sec_client_surfaces_no_network_failure():
    session = FakeSession(error=requests.Timeout("connect timed out"))

    with pytest.raises(SECEdgarError) as exc_info:
        SECEdgarClient(session=session).get_company_facts("AAPL")

    assert "timed out" in str(exc_info.value)


def test_sec_client_rejects_malformed_companyfacts_response():
    session = FakeSession(
        {
            "companyfacts": FakeResponse({"entityName": "Broken"}),
            "submissions": FakeResponse(_submissions_payload()),
        }
    )

    with pytest.raises(SECEdgarError) as exc_info:
        SECEdgarClient(session=session).get_company_facts("0000320193")

    assert "missing facts.us-gaap" in str(exc_info.value)


def test_sec_tool_saves_company_facts_csv(tmp_path, monkeypatch):
    class SuccessfulClient:
        def get_company_facts(self, identifier, periods):
            return {
                "status": "success",
                "provider": "SEC EDGAR",
                "identifier": identifier,
                "ticker": "AAPL",
                "cik": "0000320193",
                "company_name": "Apple Inc.",
                "fundamentals": [
                    {
                        "fiscal_year": 2025,
                        "revenue": 416161000000,
                        "net_income": 112010000000,
                        "capital_expenditures": 12715000000,
                        "research_and_development": 34550000000,
                        "selling_general_and_admin": 28750000000,
                        "diluted_eps": 7.46,
                        "assets": 359241000000,
                        "liabilities": 285508000000,
                        "shares": 15004697000,
                        "period_end": "2025-09-27",
                        "form": "10-K",
                    }
                ],
                "filings": [{"form": "10-K", "filing_date": "2025-10-31"}],
            }

    monkeypatch.setattr(data_engineer_tools, "SECEdgarClient", SuccessfulClient)
    monkeypatch.setattr(data_engineer_tools, "DATA_STORAGE_DIR", tmp_path)

    payload = data_engineer_tools.sec_fetch_company_facts.func(
        identifier="AAPL",
        periods=999,
        runtime=_runtime("job-sec"),
    )

    result = data_engineer_tools.json.loads(payload)
    saved_path = tmp_path / "job-sec" / "AAPL_sec_edgar_company_facts_job-sec.csv"
    assert result["status"] == "success"
    assert result["data_files"] == {"sec_company_facts": saved_path.resolve().as_posix()}
    assert result["row_counts"] == {"sec_company_facts": 1}
    assert "capital_expenditures" in result["schema_summary"]["sec_company_facts"]
    assert "research_and_development" in result["schema_summary"]["sec_company_facts"]
    assert "selling_general_and_admin" in result["schema_summary"]["sec_company_facts"]
    assert "diluted_eps" in result["schema_summary"]["sec_company_facts"]
    assert result["metadata"]["requires_api_key"] is False
    assert "do not call save_data" in result["metadata"]["handoff_guidance"]
    assert saved_path.exists()


def test_sec_tool_returns_disabled_payload(monkeypatch):
    class DisabledClient:
        def get_company_facts(self, identifier, periods):
            return {
                "status": "disabled",
                "provider": "SEC EDGAR",
                "identifier": identifier,
                "periods": periods,
            }

    monkeypatch.setattr(data_engineer_tools, "SECEdgarClient", DisabledClient)

    payload = data_engineer_tools.sec_fetch_company_facts.func(
        identifier="AAPL",
        periods=999,
        runtime=_runtime(),
    )

    result = data_engineer_tools.json.loads(payload)
    assert result == {
        "status": "disabled",
        "provider": "SEC EDGAR",
        "identifier": "AAPL",
        "periods": 10,
    }


def test_sec_tool_returns_compact_actionable_error(monkeypatch):
    class FailingClient:
        def get_company_facts(self, identifier, periods):
            raise SECEdgarError("Malformed ticker/CIK. Use 1-10 CIK digits or a ticker.")

    monkeypatch.setattr(data_engineer_tools, "SECEdgarClient", FailingClient)

    payload = data_engineer_tools.sec_fetch_company_facts.func(
        identifier="AAPL!",
        periods=5,
        runtime=_runtime(),
    )

    result = data_engineer_tools.json.loads(payload)
    assert result["status"] == "error"
    assert result["provider"] == "SEC EDGAR"
    assert result["identifier"] == "AAPL!"
    assert "Malformed ticker/CIK" in result["error"]
    assert result["retryable"] is False
    assert "valid ticker/CIK" in result["hint"]
