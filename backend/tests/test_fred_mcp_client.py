from mcp_clients.fred_mcp_client import get_fred_mcp_config


def test_fred_mcp_config_forwards_proxy_and_certificate_env(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/tmp/test-ca.pem")

    config = get_fred_mcp_config("/tmp/fred-server.js")

    env = config["fred"]["env"]
    assert env["FRED_API_KEY"] == "test-key"
    assert env["HTTPS_PROXY"] == "http://proxy.example:8080"
    assert env["NO_PROXY"] == "localhost,127.0.0.1"
    assert env["NODE_EXTRA_CA_CERTS"] == "/tmp/test-ca.pem"
    assert env["NODE_USE_ENV_PROXY"] == "1"


def test_fred_mcp_config_respects_existing_node_proxy_switch(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("NODE_USE_ENV_PROXY", "0")

    config = get_fred_mcp_config("/tmp/fred-server.js")

    assert config["fred"]["env"]["NODE_USE_ENV_PROXY"] == "0"
