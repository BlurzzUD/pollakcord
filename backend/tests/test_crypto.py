import os
import stat

import pytest

from app.config import Settings
from app.crypto.blind_index import fold, tokenize
from app.crypto.envelope import DecryptionError, Vault, seal, unseal
from app.crypto.keyring import KeyConfigurationError, KeyRing, MasterKey, decode_key_text, generate_key_text, load_keyring

from .conftest import channel_named, create_server, database_dump, first_channel, sql_rows


def make_ring(key_id="k1", previous=()):
    return KeyRing(MasterKey(key_id, decode_key_text(generate_key_text())), list(previous), decode_key_text(generate_key_text()))


def test_seal_round_trip_uses_fresh_nonces():
    key = os.urandom(32)
    first = seal(key, b"szia", b"aad")
    second = seal(key, b"szia", b"aad")
    assert first != second
    assert unseal(key, first, b"aad") == b"szia"


def test_seal_detects_tampering_and_wrong_context():
    key = os.urandom(32)
    blob = bytearray(seal(key, b"titok", b"ctx"))
    with pytest.raises(DecryptionError):
        unseal(key, bytes(blob), b"other-ctx")
    blob[-1] ^= 1
    with pytest.raises(DecryptionError):
        unseal(key, bytes(blob), b"ctx")
    with pytest.raises(DecryptionError):
        unseal(os.urandom(32), seal(key, b"x", b"ctx"), b"ctx")
    with pytest.raises(DecryptionError):
        unseal(key, b"short", b"ctx")


def test_purpose_keys_are_domain_separated():
    ring = make_ring()
    purposes = {ring.encryption_key(p) for p in ("identity", "totp", "dek-wrap", "report-snapshot")}
    assert len(purposes) == 4
    assert ring.mac("a", b"x") != ring.mac("b", b"x")
    assert ring.mac("a", b"x") == ring.mac("a", b"x")


def test_master_key_rotation_keeps_old_data_readable():
    old_master = MasterKey("k1", decode_key_text(generate_key_text()))
    pepper = decode_key_text(generate_key_text())
    old_vault = Vault(KeyRing(old_master, [], pepper))
    blob, key_id = old_vault.encrypt("identity", "Kiss Éva".encode(), b"id|1")
    new_vault = Vault(KeyRing(MasterKey("k2", decode_key_text(generate_key_text())), [old_master], pepper))
    assert new_vault.current_key_id == "k2"
    assert new_vault.decrypt("identity", blob, b"id|1", key_id) == "Kiss Éva".encode()
    with pytest.raises(KeyConfigurationError):
        Vault(KeyRing(MasterKey("k2", decode_key_text(generate_key_text())), [], pepper)).decrypt("identity", blob, b"id|1", "k1")


def test_key_text_validation():
    for bad in ("", "abc", "!!!!", generate_key_text()[:20]):
        with pytest.raises(KeyConfigurationError):
            decode_key_text(bad)


def test_production_refuses_to_start_without_keys(tmp_path):
    settings = Settings(environment="production", dev_secrets_file=tmp_path / "dev.json")
    with pytest.raises(KeyConfigurationError):
        load_keyring(settings)
    assert not (tmp_path / "dev.json").exists()


def test_development_secrets_file_is_private_and_stable(tmp_path):
    settings = Settings(environment="development", dev_secrets_file=tmp_path / "dev.json")
    first = load_keyring(settings).mac_hex("x", b"y")
    mode = stat.S_IMODE((tmp_path / "dev.json").stat().st_mode)
    assert mode == 0o600
    assert load_keyring(settings).mac_hex("x", b"y") == first


def test_keys_can_be_read_from_files(tmp_path):
    key_file, pepper_file = tmp_path / "master", tmp_path / "pepper"
    key_file.write_text(generate_key_text() + "\n")
    pepper_file.write_text(generate_key_text())
    ring = load_keyring(Settings(environment="production", master_key_file=key_file, pepper_file=pepper_file))
    assert ring.current_id == "k1"


def test_blind_index_is_accent_and_case_insensitive():
    assert fold("Tanár ÚR") == "tanar ur"
    assert tokenize("Szia, TANÁR úr! szia") == ["szia", "tanar", "ur"]
    assert tokenize("a b") == []


def test_messages_are_encrypted_in_the_database(app, api, make_user):
    owner = make_user("tulaj")
    detail = create_server(owner)
    channel = first_channel(detail, "text")
    secret_text = "kulonlegesszo-4711 egyedi mondat"
    assert owner.post(f"/channels/{channel['id']}/messages", {"content": secret_text}).status_code == 200
    dump = database_dump(app)
    assert "kulonlegesszo" not in dump
    assert "egyedi mondat" not in dump
    ciphertext = sql_rows(app, "SELECT ciphertext FROM message_contents")[0][0]
    assert len(ciphertext) == 12 + len(secret_text.encode()) + 16
    wrapped = sql_rows(app, "SELECT wrapped_key FROM data_keys")[0][0]
    assert len(wrapped) == 12 + 32 + 16
    history = owner.get(f"/channels/{channel['id']}/messages").json()
    assert history["messages"][0]["content"] == secret_text


def test_each_conversation_scope_gets_its_own_data_key(app, make_user):
    owner = make_user("tulaj")
    detail = create_server(owner)
    other = owner.post("/channels/" + first_channel(detail, "text")["id"] + "/messages", {"content": "egy"})
    assert other.status_code == 200
    second = owner.post("/servers/" + detail["id"] + "/channels", {"name": "masik", "type": "text"}).json()
    owner.post(f"/channels/{second['id']}/messages", {"content": "ketto"})
    scopes = sql_rows(app, "SELECT scope_id FROM data_keys")
    assert len({row[0] for row in scopes}) == 2


def test_swapping_ciphertext_between_messages_does_not_leak_content(app, make_user):
    owner = make_user("tulaj")
    detail = create_server(owner)
    channel = first_channel(detail, "text")
    owner.post(f"/channels/{channel['id']}/messages", {"content": "elso uzenet"})
    owner.post(f"/channels/{channel['id']}/messages", {"content": "masodik uzenet"})
    import sqlite3

    from .conftest import database_path

    connection = sqlite3.connect(database_path(app))
    rows = connection.execute("SELECT message_id, ciphertext FROM message_contents ORDER BY message_id").fetchall()
    connection.execute("UPDATE message_contents SET ciphertext=? WHERE message_id=?", (rows[1][1], rows[0][0]))
    connection.commit()
    connection.close()
    messages = owner.get(f"/channels/{channel['id']}/messages").json()["messages"]
    assert messages[0]["content"] == ""
    assert messages[1]["content"] == "masodik uzenet"


@pytest.fixture
def rotating_settings(settings):
    return settings.model_copy(update={"data_key_rotation_messages": 2})


def test_data_keys_rotate_after_the_configured_number_of_messages(rotating_settings, kreta):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import Api, ORIGIN

    app = create_app(rotating_settings, kreta_adapter=kreta)
    with TestClient(app, base_url=ORIGIN) as client:
        owner = Api(client, app)
        owner.register("diak1", "jelszo-egy", "tulaj", "Tulaj")
        detail = create_server(owner)
        channel = first_channel(detail, "text")
        for index in range(5):
            assert owner.post(f"/channels/{channel['id']}/messages", {"content": f"uzenet {index}"}).status_code == 200
        keys = sql_rows(app, "SELECT active, message_count FROM data_keys ORDER BY id")
        assert len(keys) == 3
        assert [row[0] for row in keys] == [0, 0, 1]
        history = owner.get(f"/channels/{channel['id']}/messages").json()["messages"]
        assert [m["content"] for m in history] == [f"uzenet {i}" for i in range(5)]
