import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthUser, get_current_user
from api.routes.reports import get_report
from core.database import Base, ResearchJob, SavedReport
from services import report_library, research_jobs
from services.research_jobs import run_job_background
from services.research_types import JobState, JobStatus


class _Request:
    def __init__(self, cookie: str | None = None):
        self.headers = {"cookie": cookie} if cookie else {}


class _FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    status = 200
    payload = {"user": {"id": "user_1", "email": "a@example.com", "name": "A"}}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def get(self, *_args, **_kwargs):
        return _FakeResponse(self.status, self.payload)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        yield session


@pytest.mark.asyncio
async def test_auth_dependency_rejects_missing_cookie():
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_Request())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_dependency_rejects_invalid_session(monkeypatch):
    _FakeSession.status = 401
    _FakeSession.payload = {}
    monkeypatch.setattr("api.dependencies.aiohttp.ClientSession", _FakeSession)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_Request("better-auth.session=bad"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_dependency_accepts_valid_session(monkeypatch):
    _FakeSession.status = 200
    _FakeSession.payload = {"user": {"id": "user_1", "email": "a@example.com", "name": "A"}}
    monkeypatch.setattr("api.dependencies.aiohttp.ClientSession", _FakeSession)

    user = await get_current_user(_Request("better-auth.session=ok"))
    assert user.id == "user_1"
    assert user.email == "a@example.com"


@pytest.mark.asyncio
async def test_user_can_fetch_own_saved_report(db_session):
    db_session.add(
        ResearchJob(id="job_1", user_id="user_1", query="q", status=JobStatus.COMPLETED.value)
    )
    db_session.add(
        SavedReport(
            job_id="job_1",
            user_id="user_1",
            title="Own report",
            query="q",
            report_json={"title": "Own report", "job_id": "job_1"},
        )
    )
    db_session.commit()

    report = await get_report("job_1", AuthUser(id="user_1"), db_session)
    assert report["title"] == "Own report"


@pytest.mark.asyncio
async def test_user_cannot_fetch_another_users_report(db_session):
    db_session.add(
        ResearchJob(id="job_1", user_id="user_2", query="q", status=JobStatus.COMPLETED.value)
    )
    db_session.add(
        SavedReport(
            job_id="job_1",
            user_id="user_2",
            title="Other report",
            query="q",
            report_json={"title": "Other report", "job_id": "job_1"},
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_report("job_1", AuthUser(id="user_1"), db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_completed_background_job_auto_saves_report(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        db.add(ResearchJob(id="job_1", user_id="user_1", query="q", status=JobStatus.RUNNING.value))
        db.commit()

    output_dir = tmp_path / "outputs"
    report_dir = output_dir / "job_1"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps({"job_id": "job_1", "title": "Saved", "query": "q"}),
        encoding="utf-8",
    )

    async def fake_stream_research(**_kwargs):
        if False:
            yield {}

    monkeypatch.setattr(research_jobs, "stream_research", fake_stream_research)
    monkeypatch.setattr(research_jobs, "SessionLocal", Session)
    monkeypatch.setattr(research_jobs, "OUTPUT_BASE_DIR", output_dir)
    monkeypatch.setattr(report_library, "OUTPUT_BASE_DIR", output_dir)
    monkeypatch.setattr("services.job_status.OUTPUT_BASE_DIR", output_dir)
    monkeypatch.setattr(research_jobs, "write_job_status", lambda *_args, **_kwargs: None)

    state = JobState(job_id="job_1", user_id="user_1", query="q", status=JobStatus.RUNNING)
    await run_job_background("job_1", "user_1", "q", [], object(), state)

    with Session() as db:
        saved = db.query(SavedReport).filter_by(job_id="job_1", user_id="user_1").one()
        assert saved.title == "Saved"
        assert saved.report_json["job_id"] == "job_1"
        assert db.get(ResearchJob, "job_1").status == JobStatus.COMPLETED.value
