from pathlib import Path

from agents.orchestrator import GuardedLocalShellBackend
from services.stream_events import parse_graph_update, sanitize_stream_value


def test_guarded_backend_denies_env_file_reads(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    backend = GuardedLocalShellBackend(
        root_dir=tmp_path,
        virtual_mode=False,
        env={"PATH": "/usr/bin:/bin"},
        inherit_env=False,
    )

    result = backend.read(str(env_file))

    assert result.error
    assert "sensitive local credential files" in result.error
    assert result.file_data is None


def test_guarded_backend_denies_env_shell_commands(tmp_path: Path):
    backend = GuardedLocalShellBackend(
        root_dir=tmp_path,
        virtual_mode=False,
        env={"PATH": "/usr/bin:/bin"},
        inherit_env=False,
    )

    result = backend.execute("cat .env")

    assert result.exit_code == 1
    assert "sensitive local credential files" in result.output


def test_stream_parser_suppresses_sensitive_tool_call_args():
    events, _ = parse_graph_update(
        ["orchestrator:abc"],
        {
            "messages": [
                {
                    "type": "ai",
                    "tool_calls": [
                        {
                            "name": "read_file",
                            "args": {"file_path": "/repo/backend/.env"},
                            "id": "call_1",
                        },
                        {
                            "name": "read_file",
                            "args": {"file_path": "/repo/backend/outputs/job/report.json"},
                            "id": "call_2",
                        },
                    ],
                }
            ]
        },
        None,
    )

    tool_calls = [event for event in events if event.get("type") == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["args"]["file_path"] == "/repo/backend/outputs/job/report.json"


def test_stream_sanitizer_redacts_secret_values_and_paths():
    redacted = sanitize_stream_value(
        {
            "summary": "OPENAI_API_KEY=sk-test\nRead /repo/backend/.env",
            "token": "abc123",
        }
    )

    assert "sk-test" not in redacted["summary"]
    assert ".env" not in redacted["summary"]
    assert redacted["token"] == "[redacted]"
