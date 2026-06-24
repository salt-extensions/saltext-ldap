"""
Test cases for saltext.ldap.modules.ldap3

Focused on :py:func:`ldap3.change`, which translates a before/after view of an
entry into an LDAP modlist. These assert the modlist actually handed to
``modify_s`` so the wholesale-``MOD_REPLACE`` path (used by ``ldap.managed``'s
``replace:`` directive for X-ORDERED ``cn=config`` attributes) is exercised
directly, not only through the state module or a live server.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from saltext.ldap.modules import ldap3

try:
    import ldap

    HAS_LDAP = True
except ImportError:
    HAS_LDAP = False

# python-ldap is an optional backend dependency; skip when it is not installed,
# matching the gating used by the auth module's unit tests.
pytestmark = [
    pytest.mark.skipif(not HAS_LDAP, reason="Install python-ldap for this test"),
]


@pytest.fixture
def configure_loader_modules():
    return {ldap3: {}}


class _RecordingLDAPObject:
    """Underlying LDAP connection that records modify_s calls."""

    def __init__(self):
        self.modify_calls = []

    def modify_s(self, dn, modlist):
        self.modify_calls.append((dn, modlist))


@pytest.fixture
def conn():
    """Patch ldap3.connect so change() operates on a recording connection."""
    rec = _RecordingLDAPObject()
    with patch.object(ldap3, "connect", MagicMock(return_value=SimpleNamespace(c=rec))):
        yield rec


def _modlist(conn):
    assert len(conn.modify_calls) == 1
    return conn.modify_calls[0][1]


def test_change_emits_mod_replace_for_replace_attr(conn):
    """An attribute named in ``replace_attrs`` is sent as a single atomic
    ``MOD_REPLACE`` carrying the ``after`` values, not an add/delete diff."""
    result = ldap3.change(
        {},
        "olcDatabase={1}mdb,cn=config",
        {"olcSyncRepl": ["{0}rid=001"]},
        {"olcSyncRepl": ["rid=001", "rid=002"]},
        replace_attrs={"olcSyncRepl"},
    )
    assert result is True
    assert _modlist(conn) == [(ldap.MOD_REPLACE, "olcSyncRepl", [b"rid=001", b"rid=002"])]


def test_change_replace_attr_absent_from_after_emits_empty_mod_replace(conn):
    """A replaced attribute missing from ``after`` becomes an empty
    ``MOD_REPLACE``, which deletes the attribute outright."""
    ldap3.change(
        {},
        "olcDatabase={1}mdb,cn=config",
        {"olcSyncRepl": ["{0}rid=001"]},
        {},
        replace_attrs={"olcSyncRepl"},
    )
    assert _modlist(conn) == [(ldap.MOD_REPLACE, "olcSyncRepl", [])]


def test_change_mixes_replace_attr_and_diffed_attr(conn):
    """Attributes not in ``replace_attrs`` still go through the add/delete
    diff while the replaced attribute is sent as ``MOD_REPLACE``."""
    ldap3.change(
        {},
        "cn=x,dc=example,dc=com",
        {"olcSyncRepl": ["{0}rid=001"], "description": ["old"]},
        {"olcSyncRepl": ["rid=001"], "description": ["new"]},
        replace_attrs={"olcSyncRepl"},
    )
    modlist = _modlist(conn)
    assert (ldap.MOD_REPLACE, "olcSyncRepl", [b"rid=001"]) in modlist
    # description is diffed, never wholesale-replaced.
    desc_ops = [(op, attr, vals) for (op, attr, vals) in modlist if attr == "description"]
    assert (ldap.MOD_DELETE, "description", None) in desc_ops
    assert (ldap.MOD_ADD, "description", [b"new"]) in desc_ops
    assert not any(op == ldap.MOD_REPLACE for (op, attr, _) in modlist if attr == "description")


def test_change_without_replace_attrs_is_pure_diff(conn):
    """With no ``replace_attrs`` the behaviour is unchanged: a plain
    ``modifyModlist`` add/delete diff and never a ``MOD_REPLACE``."""
    ldap3.change(
        {},
        "cn=x,dc=example,dc=com",
        {"description": ["old"]},
        {"description": ["new"]},
    )
    modlist = _modlist(conn)
    assert modlist == [
        (ldap.MOD_DELETE, "description", None),
        (ldap.MOD_ADD, "description", [b"new"]),
    ]
    assert not any(op == ldap.MOD_REPLACE for (op, _, _) in modlist)


def test_change_backend_error_is_converted(conn):
    """A backend ``ldap.LDAPError`` from modify_s is wrapped as ``LDAPError``."""
    conn.modify_s = MagicMock(side_effect=ldap.LDAPError("boom"))
    with pytest.raises(ldap3.LDAPError):
        ldap3.change(
            {},
            "cn=x,dc=example,dc=com",
            {"description": ["old"]},
            {"description": ["new"]},
        )
