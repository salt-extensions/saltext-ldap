"""
:codeauthor: Jayesh Kariya <jayeshk@saltstack.com>

Test cases for saltext.ldap.modules.ldap_mod
"""

import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from saltext.ldap.modules import ldap_mod


@pytest.fixture
def configure_loader_modules():
    return {ldap_mod: {}}


class _RecordingConn:
    """A stand-in LDAP connection that records what search_s was called with."""

    def __init__(self, return_value=None):
        self.calls = []
        self.return_value = [] if return_value is None else return_value

    def search_s(self, bdn, scope, _filter, attrs):
        self.calls.append((bdn, scope, _filter, attrs))
        return self.return_value


# ---------------------------------------------------------------------------
# _config
# ---------------------------------------------------------------------------


def test__config_prefers_kwargs_over_salt_config():
    """A value passed as a kwarg should win over the master config."""
    config_option = MagicMock(return_value="from-config")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        assert ldap_mod._config("server", server="from-kwargs") == "from-kwargs"
    config_option.assert_not_called()


def test__config_falls_back_to_salt_config_option():
    """Without a kwarg, _config should pull from __salt__['config.option']."""
    config_option = MagicMock(return_value="ldap.example.com")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        assert ldap_mod._config("server") == "ldap.example.com"
    config_option.assert_called_once_with("ldap.server")


def test__config_uses_key_alias_when_provided():
    """The `key` parameter remaps the config option name."""
    config_option = MagicMock(return_value="dc=acme,dc=com")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        ldap_mod._config("dn", key="basedn")
    config_option.assert_called_once_with("ldap.basedn")


def test__config_decodes_bytes_to_str():
    """Bytes values returned by config.option must be decoded."""
    config_option = MagicMock(return_value=b"dc=example,dc=com")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        result = ldap_mod._config("basedn")
    assert result == "dc=example,dc=com"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_returns_results_count_and_timing():
    """search should return the LDAP result, a count, and timing metadata."""
    conn = _RecordingConn(return_value=[("cn=a,dc=x", {"cn": ["a"]})])
    config_option = MagicMock(return_value=True)
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=conn)):
            with patch.object(time, "time", MagicMock(return_value=8e-04)):
                result = ldap_mod.search(filter="(cn=a)")
    assert result == {
        "count": 1,
        "results": [("cn=a,dc=x", {"cn": ["a"]})],
        "time": {"raw": "0.0", "human": "0.0ms"},
    }


def test_search_uses_kwargs_for_dn_and_scope():
    """Explicit dn/scope kwargs override the config lookups."""
    conn = _RecordingConn()
    config_option = MagicMock(return_value="should-not-be-used")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=conn)):
            with patch.object(time, "time", MagicMock(return_value=0.0)):
                ldap_mod.search(filter="(cn=*)", dn="dc=explicit,dc=com", scope=1, attrs=["cn"])
    assert conn.calls == [("dc=explicit,dc=com", 1, "(cn=*)", ["cn"])]


def test_search_falls_back_to_config_for_dn_scope_attrs():
    """Without kwargs, dn/scope/attrs are pulled from ldap.* config options."""
    conn = _RecordingConn()
    lookups = {"ldap.basedn": "dc=cfg,dc=com", "ldap.scope": "2", "ldap.attrs": ["cn"]}
    config_option = MagicMock(side_effect=lambda name: lookups[name])
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=conn)):
            with patch.object(time, "time", MagicMock(return_value=0.0)):
                ldap_mod.search(filter="(cn=*)")
    assert conn.calls == [("dc=cfg,dc=com", 2, "(cn=*)", ["cn"])]


def test_search_empty_attrs_string_overrides_to_all_attributes():
    """attrs='' is the CLI escape hatch to request all attributes."""
    conn = _RecordingConn()
    config_option = MagicMock(return_value="dc=cfg,dc=com")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=conn)):
            with patch.object(time, "time", MagicMock(return_value=0.0)):
                ldap_mod.search(filter="(cn=*)", dn="dc=x", scope=2, attrs="")
    # attrs=None tells python-ldap to return every attribute
    assert conn.calls[0][3] is None


def test_search_formats_slow_queries_in_seconds():
    """Searches taking >= 200ms are reported in seconds, not milliseconds."""
    conn = _RecordingConn(return_value=[])
    times = iter([100.0, 100.5])  # start, end → 0.5s elapsed
    config_option = MagicMock(return_value="dc=x")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=conn)):
            with patch.object(time, "time", lambda: next(times)):
                result = ldap_mod.search(filter="(cn=*)", dn="dc=x", scope=2, attrs=["cn"])
    assert result["time"]["human"].endswith("s")
    assert not result["time"]["human"].endswith("ms")
    assert result["count"] == 0


def test_search_passes_connection_kwargs_to__connect():
    """Connection kwargs (server, port, bindpw, ...) flow through to _connect."""
    conn = _RecordingConn()
    connect = MagicMock(return_value=conn)
    config_option = MagicMock(return_value="dc=x")
    with patch.dict(ldap_mod.__salt__, {"config.option": config_option}):
        with patch.object(ldap_mod, "_connect", connect):
            with patch.object(time, "time", MagicMock(return_value=0.0)):
                ldap_mod.search(
                    filter="(cn=*)",
                    dn="dc=x",
                    scope=2,
                    attrs=["cn"],
                    server="other.example.com",
                    bindpw="hunter2",
                )
    _, kwargs = connect.call_args
    assert kwargs["server"] == "other.example.com"
    assert kwargs["bindpw"] == "hunter2"
