import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.crypto.envelope import Vault
from app.crypto.keyring import KeyRing, MasterKey, decode_key_text, generate_key_text
from app.errors import AppError
from app.integrations.kreta import adapter as kreta_adapter
from app.integrations.kreta.adapter import (
    KretaConfigurationError,
    KretaOutcome,
    KretaResult,
    KretaScriptAdapter,
    interpret_output,
    parse_full_name,
    sha256_of_file,
)
from app.integrations.kreta.flows import FlowIntent, FlowState, KretaFlowStore, validate_credentials

from .fakes import FakeKretaAdapter

BACKEND = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND / "app" / "integrations" / "kreta" / "script" / "kreta_login_from_dumps.py"
PINNED_DIGEST = (BACKEND / "app" / "integrations" / "kreta" / "script.sha256").read_text().split()[0]
FAKE_TRANSPORT = Path(__file__).resolve().parent / "kreta_fake"
DISTINCT_PASSWORD = "Zq9-never-log-me-4711"


def real_adapter(scenario: str = "ok", timeout: float = 25.0, **env: str) -> KretaScriptAdapter:
    environment = {"PYTHONPATH": str(FAKE_TRANSPORT), "FAKE_KRETA_SCENARIO": scenario, "FAKE_KRETA_PASS": DISTINCT_PASSWORD, **env}
    return KretaScriptAdapter(SCRIPT, extra_env=environment, process_timeout=timeout)


def run(coroutine):
    return asyncio.run(coroutine)


def test_supplied_script_is_unmodified():
    assert sha256_of_file(SCRIPT) == PINNED_DIGEST


def test_adapter_refuses_a_script_that_does_not_match_the_pinned_digest():
    adapter = KretaScriptAdapter(SCRIPT, expected_sha256="0" * 64)
    with pytest.raises(KretaConfigurationError):
        adapter.verify_script()
    assert KretaScriptAdapter(SCRIPT, expected_sha256=PINNED_DIGEST).verify_script() == PINNED_DIGEST


def test_adapter_reports_missing_script(tmp_path):
    with pytest.raises(KretaConfigurationError):
        KretaScriptAdapter(tmp_path / "missing.py").verify_script()


def test_script_still_contains_the_markers_the_adapter_depends_on():
    source = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        kreta_adapter.TWO_FACTOR_PROMPT,
        "Student name returned by API: ",
        kreta_adapter.DONE_MARKER,
        kreta_adapter.BAD_PASSWORD_MARKER,
        kreta_adapter.BAD_TWO_FACTOR_MARKER,
        kreta_adapter.LICENSE_MARKER,
        "Username (UserName): ",
        "Password (visible): ",
    ):
        assert marker in source


def test_real_script_identifies_user_without_two_factor_and_drops_guardian_name():
    session, result = run(real_adapter().start("diak123", DISTINCT_PASSWORD))
    assert session is None
    assert result == KretaResult(KretaOutcome.IDENTIFIED, "Piti Péter")


def test_real_script_rejects_wrong_password():
    session, result = run(real_adapter().start("diak123", "rossz-jelszo"))
    assert session is None
    assert result.outcome is KretaOutcome.INVALID_CREDENTIALS
    assert result.full_name is None


def test_real_script_two_factor_success():
    async def scenario():
        adapter = real_adapter("twofactor")
        session, first = await adapter.start("diak123", DISTINCT_PASSWORD)
        assert first.outcome is KretaOutcome.TWO_FACTOR_REQUIRED
        assert session is not None and session.process.returncode is None
        return session, await adapter.submit_two_factor(session, "123456")

    session, result = run(scenario())
    assert result == KretaResult(KretaOutcome.IDENTIFIED, "Piti Péter")
    assert session.closed and session.process.returncode is not None


def test_real_script_two_factor_failure():
    async def scenario():
        adapter = real_adapter("twofactor")
        session, _ = await adapter.start("diak123", DISTINCT_PASSWORD)
        return await adapter.submit_two_factor(session, "000000")

    assert run(scenario()).outcome is KretaOutcome.INVALID_TWO_FACTOR


def test_real_script_expired_licence_is_reported_as_unavailable():
    _, result = run(real_adapter("license").start("diak123", DISTINCT_PASSWORD))
    assert result.outcome is KretaOutcome.SERVICE_UNAVAILABLE


def test_hanging_script_is_killed_after_the_timeout():
    started = time.monotonic()
    _, result = run(real_adapter("hang", timeout=2).start("diak123", DISTINCT_PASSWORD))
    assert result.outcome is KretaOutcome.SERVICE_UNAVAILABLE
    assert time.monotonic() - started < 15


def test_credentials_never_reach_logs_or_results(caplog):
    caplog.set_level(logging.DEBUG)
    _, result = run(real_adapter().start("diak123", DISTINCT_PASSWORD))
    assert DISTINCT_PASSWORD not in caplog.text
    assert DISTINCT_PASSWORD not in repr(result)
    assert "diak123" not in repr(result)


def test_scratch_directory_is_removed_and_process_is_gone():
    before = {p.name for p in Path(tempfile.gettempdir()).glob("pollakcord-kreta-*")}

    async def scenario():
        adapter = real_adapter("twofactor")
        session, _ = await adapter.start("diak123", DISTINCT_PASSWORD)
        workdir, pid = session.workdir, session.process.pid
        assert workdir.exists()
        await adapter.abort(session)
        return workdir, pid

    workdir, pid = run(scenario())
    assert not workdir.exists()
    assert not Path(f"/proc/{pid}").exists()
    after = {p.name for p in Path(tempfile.gettempdir()).glob("pollakcord-kreta-*")}
    assert after <= before


def test_child_process_does_not_inherit_server_secrets(monkeypatch):
    monkeypatch.setenv("POLLAKCORD_MASTER_KEY", "top-secret-master-key")
    monkeypatch.setenv("POLLAKCORD_PEPPER", "top-secret-pepper")

    async def scenario():
        adapter = real_adapter("twofactor")
        session, _ = await adapter.start("diak123", DISTINCT_PASSWORD)
        environment = Path(f"/proc/{session.process.pid}/environ").read_bytes()
        await adapter.abort(session)
        return environment

    environment = run(scenario())
    assert b"top-secret" not in environment
    assert b"POLLAKCORD" not in environment


def test_parse_full_name_keeps_only_the_person_and_validates_characters():
    assert parse_full_name("Piti Péter (Szabó Erzsébet)") == "Piti Péter"
    assert parse_full_name("  Dr.  Kovács-Nagy   Ádám ") == "Dr. Kovács-Nagy Ádám"
    assert parse_full_name("Ő Ű") is not None
    for bad in ("", "A", "Név123", "Név\u202eEvil", "<script>alert(1)</script>", "x" * 130):
        assert parse_full_name(bad) is None


def test_output_interpretation_ignores_forged_name_lines():
    forged = "Student name returned by API: Mallory Mal\n=== Done ===\n"
    assert interpret_output(forged, 0).outcome is KretaOutcome.FAILED
    early = "=== Done ===\nStudent name returned by API: Valós Név\n"
    assert interpret_output(early, 1).outcome is not KretaOutcome.IDENTIFIED
    good = "x\n=== Done ===\nStudent name returned by API: Valós Név (Anya)\n"
    assert interpret_output(good, 0) == KretaResult(KretaOutcome.IDENTIFIED, "Valós Név")


def test_stdin_injection_through_credentials_is_rejected():
    for username, password in (("diak\nhacker", "x"), ("diak", "pw\r\nsecond"), ("diak", "pw\x00"), ("", "pw"), ("diak", " ")):
        with pytest.raises(AppError):
            validate_credentials(username, password)
    assert validate_credentials(" diak ", " pw ") == ("diak", "pw")


@pytest.fixture
def vault() -> Vault:
    return Vault(KeyRing(MasterKey("k1", decode_key_text(generate_key_text())), [], decode_key_text(generate_key_text())))


def store(vault, adapter, ttl=60, limit=2) -> KretaFlowStore:
    return KretaFlowStore(adapter, vault, namespace="test", two_factor_ttl=ttl, max_concurrent=limit)


def test_flow_store_happy_path_and_single_use(vault):
    async def scenario():
        flows = store(vault, FakeKretaAdapter())
        view = await flows.begin(FlowIntent.REGISTER, "diak1", "jelszo-egy")
        assert view.state is FlowState.IDENTIFIED and view.full_name == "Kiss Éva"
        await flows.decide(view.token, True)
        flow = flows.peek_confirmed(view.token, FlowIntent.REGISTER)
        assert flow.identity_hash == flows.identity_hash("DIAK1 ")
        with pytest.raises(AppError):
            flows.peek_confirmed(view.token, FlowIntent.RECOVER)
        flows.finish(view.token)
        with pytest.raises(AppError):
            flows.peek_confirmed(view.token, FlowIntent.REGISTER)

    run(scenario())


def test_flow_store_rejection_aborts_and_forgets(vault):
    async def scenario():
        adapter = FakeKretaAdapter()
        flows = store(vault, adapter)
        view = await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        assert view.state is FlowState.AWAITING_TWO_FACTOR
        view = await flows.submit_two_factor(view.token, "123456")
        await flows.decide(view.token, False)
        with pytest.raises(AppError):
            await flows.decide(view.token, True)

    run(scenario())


def test_flow_store_limits_concurrent_processes_and_releases_slots(vault):
    async def scenario():
        adapter = FakeKretaAdapter()
        flows = store(vault, adapter, limit=2)
        first = await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        with pytest.raises(AppError) as busy:
            await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        assert busy.value.code == "kreta_busy"
        await flows.cancel(first.token)
        again = await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        assert again.state is FlowState.AWAITING_TWO_FACTOR
        assert adapter.sessions[0].aborted

    run(scenario())


def test_flow_store_sweeps_expired_flows_and_kills_their_processes(vault):
    async def scenario():
        adapter = FakeKretaAdapter()
        flows = store(vault, adapter, ttl=0.01)
        view = await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        await asyncio.sleep(0.05)
        await flows.sweep()
        assert adapter.sessions[0].aborted
        with pytest.raises(AppError):
            await flows.submit_two_factor(view.token, "123456")

    run(scenario())


def test_flow_store_failed_two_factor_destroys_the_flow(vault):
    async def scenario():
        flows = store(vault, FakeKretaAdapter())
        view = await flows.begin(FlowIntent.REGISTER, "diak2", "jelszo-ketto")
        with pytest.raises(AppError) as failure:
            await flows.submit_two_factor(view.token, "999999")
        assert failure.value.code == "kreta_invalid_two_factor"
        with pytest.raises(AppError):
            await flows.submit_two_factor(view.token, "123456")

    run(scenario())


def test_settings_default_to_the_bundled_script():
    assert Settings().kreta_script_path.name == "kreta_login_from_dumps.py"
    assert Settings().kreta_script_path.exists()
