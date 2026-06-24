"""Test cases for the ``ldap`` state module

This code is gross.  I started out trying to remove some of the
duplicate code in the test cases, and before I knew it the test code
was an ugly second implementation.

I'm leaving it for now, but this should really be gutted and replaced
with something sensible.
"""

import copy
import logging

import attr
import pytest
from salt.utils.oset import OrderedSet
from salt.utils.stringutils import to_bytes

import saltext.ldap.states.ldap_mod

log = logging.getLogger(__name__)


class LDAPError(Exception):
    """Stand-in for ldap3.LDAPError used by tests that simulate LDAP
    operation failures.

    ``managed()`` resolves the exception class via
    ``inspect.getmodule(connect).LDAPError`` where ``connect`` is the
    callable registered as ``__salt__["ldap3.connect"]``. Because the
    dummy ``connect`` is a method of ``LdapDB`` defined in this module,
    ``inspect.getmodule()`` returns this test module, so the symbol must
    live here for the ``except`` clause to resolve.
    """


# emulates the LDAP database.  each key is the DN of an entry and it
# maps to a dict which maps attribute names to sets of values.
@attr.s
class LdapDB:
    db = attr.ib(init=False, default=attr.Factory(dict))

    def dummy_connect(self, connect_spec):
        return _dummy_ctx()

    def dummy_search(self, connect_spec, base, scope, attrlist):
        if base not in self.db:
            return {}
        return {
            base: {
                attr: list(self.db[base][attr])
                for attr in self.db[base]
                if len(self.db[base][attr])
                and (attrlist is None or attr in attrlist or "*" in attrlist)
            }
        }

    def dummy_add(self, connect_spec, dn, attributes):
        assert dn not in self.db
        assert attributes
        self.db[dn] = {}
        for attr, vals in attributes.items():
            assert vals
            self.db[dn][attr] = OrderedSet(vals)
        return True

    def dummy_delete(self, connect_spec, dn):
        assert dn in self.db
        del self.db[dn]
        return True

    def dummy_change(self, connect_spec, dn, before, after, replace_attrs=None):
        assert before != after
        assert before
        assert after
        assert dn in self.db
        e = self.db[dn]
        replace_attrs = set(replace_attrs or ())
        # The state may pass a normalized view of ``before`` for attrs being
        # wholesale-replaced (e.g. X-ORDERED ``{N}`` prefix stripped), which
        # is fine because the backend ignores ``before`` for those attrs and
        # emits an atomic MOD_REPLACE. Only enforce the sanity invariant for
        # attrs that go through the add/delete diff path.
        e_diff = {a: v for a, v in e.items() if a not in replace_attrs}
        before_diff = {a: v for a, v in before.items() if a not in replace_attrs}
        assert e_diff == before_diff
        all_attrs = OrderedSet()
        all_attrs.update(before)
        all_attrs.update(after)
        directives = []
        for attr in all_attrs:
            if attr in replace_attrs:
                # Caller asked for a wholesale replace; mirror the real ldap3
                # backend, which emits MOD_REPLACE rather than an add/delete
                # diff for these attributes.
                directives.append(("replace", attr, after.get(attr, ())))
            elif attr not in before:
                assert attr in after
                assert after[attr]
                directives.append(("add", attr, after[attr]))
            elif attr not in after:
                assert attr in before
                assert before[attr]
                directives.append(("delete", attr, ()))
            else:
                assert before[attr]
                assert after[attr]
                to_del = before[attr] - after[attr]
                if to_del:
                    directives.append(("delete", attr, to_del))
                to_add = after[attr] - before[attr]
                if to_add:
                    directives.append(("add", attr, to_add))
        return self.dummy_modify(connect_spec, dn, directives)

    def dummy_modify(self, connect_spec, dn, directives):
        assert dn in self.db
        e = self.db[dn]
        for op, attr, vals in directives:
            if op == "add":
                assert vals
                existing_vals = e.setdefault(attr, OrderedSet())
                for val in vals:
                    assert val not in existing_vals
                    existing_vals.add(val)
            elif op == "delete":
                assert attr in e
                existing_vals = e[attr]
                assert existing_vals
                if not vals:
                    del e[attr]
                    continue
                for val in vals:
                    assert val in existing_vals
                    existing_vals.remove(val)
                if not existing_vals:
                    del e[attr]
            elif op == "replace":
                e.pop(attr, None)
                # MOD_REPLACE with an empty value list deletes the attribute.
                if vals:
                    e[attr] = OrderedSet(vals)
            else:
                raise ValueError()
        return True

    def dump_db(self, d=None):
        if d is None:
            d = self.db
        return {dn: {attr: list(d[dn][attr]) for attr in d[dn]} for dn in d}


@pytest.fixture
def db():
    return LdapDB()


@pytest.fixture
def complex_db(db):
    db.db = {
        "dnfoo": {
            "attrfoo1": OrderedSet(
                (
                    b"valfoo1.1",
                    b"valfoo1.2",
                )
            ),
            "attrfoo2": OrderedSet((b"valfoo2.1",)),
        },
        "dnbar": {
            "attrbar1": OrderedSet(
                (
                    b"valbar1.1",
                    b"valbar1.2",
                )
            ),
            "attrbar2": OrderedSet((b"valbar2.1",)),
        },
    }
    return db


@pytest.fixture
def no_change_complex_db(db):
    db.db = {
        "dnfoo": {
            "attrfoo1": OrderedSet(
                (
                    b"valfoo1.1",
                    b"valfoo1.2",
                )
            ),
            "attrfoo2": OrderedSet((b"valfoo2.1",)),
        },
        "dnbar": {
            "attrbar1": OrderedSet(
                (
                    b"valbar1.1",
                    b"valbar1.2",
                )
            ),
            "attrbar2": OrderedSet((b"valbar2.1",)),
        },
    }
    return db


# pylint: disable-next=invalid-name
class _dummy_ctx:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.fixture
def configure_loader_modules(db):
    salt_dunder = {
        "ldap3.connect": db.dummy_connect,
        "ldap3.search": db.dummy_search,
        "ldap3.add": db.dummy_add,
        "ldap3.delete": db.dummy_delete,
        "ldap3.change": db.dummy_change,
        "ldap3.modify": db.dummy_modify,
    }
    return {saltext.ldap.states.ldap_mod: {"__opts__": {"test": False}, "__salt__": salt_dunder}}


def _test_helper(init_db, expected_ret, replace, delete_others=False, attrlist=None):
    old = init_db.dump_db()
    new = init_db.dump_db()
    expected_db = copy.deepcopy(init_db.db)
    for dn, attrs in replace.items():
        for attr, vals in attrs.items():
            vals = [to_bytes(val) for val in vals]
            if vals:
                new.setdefault(dn, {})[attr] = list(OrderedSet(vals))
                expected_db.setdefault(dn, {})[attr] = OrderedSet(vals)
            elif dn in expected_db:
                new[dn].pop(attr, None)
                expected_db[dn].pop(attr, None)
        if not expected_db.get(dn, {}):
            new.pop(dn, None)
            expected_db.pop(dn, None)
    if delete_others:
        dn_to_delete = OrderedSet()
        for dn, attrs in expected_db.items():
            if dn in replace:
                to_delete = OrderedSet()
                for attr, vals in attrs.items():
                    if attr not in replace[dn]:
                        to_delete.add(attr)
                for attr in to_delete:
                    del attrs[attr]
                    del new[dn][attr]
                if not attrs:
                    dn_to_delete.add(dn)
        for dn in dn_to_delete:
            del new[dn]
            del expected_db[dn]
    name = "ldapi:///"
    expected_ret["name"] = name
    expected_ret.setdefault("result", True)
    expected_ret.setdefault("comment", "Successfully updated LDAP entries")
    expected_ret.setdefault(
        "changes",
        {
            dn: {
                "old": (
                    {
                        attr: vals
                        for attr, vals in old[dn].items()
                        if vals != new.get(dn, {}).get(attr, ())
                    }
                    if dn in old
                    else None
                ),
                "new": (
                    {
                        attr: vals
                        for attr, vals in new[dn].items()
                        if vals != old.get(dn, {}).get(attr, ())
                    }
                    if dn in new
                    else None
                ),
            }
            for dn in replace
            if old.get(dn, {}) != new.get(dn, {})
        },
    )
    entries = [
        {dn: [{"replace": attrs}, {"delete_others": delete_others}]}
        for dn, attrs in replace.items()
    ]
    actual = saltext.ldap.states.ldap_mod.managed(name, entries, attrlist=attrlist)
    assert expected_ret == actual
    assert expected_db == init_db.db


def _test_helper_success(db, replace, delete_others=False, attrlist=None):
    _test_helper(db, {}, replace, delete_others, attrlist)


def _test_helper_nochange(db, replace, delete_others=False):
    expected = {
        "changes": {},
        "comment": "LDAP entries already set",
    }
    _test_helper(db, expected, replace, delete_others)


def _test_helper_add(db, expected_ret, add_items, delete_others=False, attrlist=None):
    old = db.dump_db()
    new = db.dump_db()
    expected_db = copy.deepcopy(db.db)
    for dn, attrs in add_items.items():
        for attr, vals in attrs.items():
            vals = [to_bytes(val) for val in vals]

            vals.extend(old.get(dn, {}).get(attr, OrderedSet()))
            vals.sort()

            if vals:
                new.setdefault(dn, {})[attr] = list(OrderedSet(vals))
                expected_db.setdefault(dn, {})[attr] = OrderedSet(vals)
            elif dn in expected_db:
                new[dn].pop(attr, None)
                expected_db[dn].pop(attr, None)
        if not expected_db.get(dn, {}):
            new.pop(dn, None)
            expected_db.pop(dn, None)
    if delete_others:
        dn_to_delete = OrderedSet()
        for dn, attrs in expected_db.items():
            if dn in add_items:
                to_delete = OrderedSet()
                for attr, vals in attrs.items():
                    if attr not in add_items[dn]:
                        to_delete.add(attr)
                for attr in to_delete:
                    del attrs[attr]
                    del new[dn][attr]
                if not attrs:
                    dn_to_delete.add(dn)
        for dn in dn_to_delete:
            del new[dn]
            del expected_db[dn]
    name = "ldapi:///"
    expected_ret["name"] = name
    expected_ret.setdefault("result", True)
    expected_ret.setdefault("comment", "Successfully updated LDAP entries")
    expected_ret.setdefault(
        "changes",
        {
            dn: {
                "old": (
                    {
                        attr: vals
                        for attr, vals in old[dn].items()
                        if vals != new.get(dn, {}).get(attr, ())
                    }
                    if dn in old
                    else None
                ),
                "new": (
                    {
                        attr: vals
                        for attr, vals in new[dn].items()
                        if vals != old.get(dn, {}).get(attr, ())
                    }
                    if dn in new
                    else None
                ),
            }
            for dn in add_items
            if old.get(dn, {}) != new.get(dn, {})
        },
    )
    entries = [
        {dn: [{"add": attrs}, {"delete_others": delete_others}]} for dn, attrs in add_items.items()
    ]
    actual = saltext.ldap.states.ldap_mod.managed(name, entries, attrlist=attrlist)
    assert expected_ret == actual
    assert expected_db == db.db


def _test_helper_success_add(db, add_items, delete_others=False, attrlist=None):
    _test_helper_add(db, {}, add_items, delete_others, attrlist)


def test_managed_empty(db):
    name = "ldapi:///"
    expected = {
        "name": name,
        "changes": {},
        "result": True,
        "comment": "LDAP entries already set",
    }
    actual = saltext.ldap.states.ldap_mod.managed(name, {})
    assert expected == actual


def test_managed_add_entry(db):
    _test_helper_success_add(db, {"dummydn": {"foo": ["bar", "baz"]}})


def test_managed_add_attr(complex_db):
    _test_helper_success_add(complex_db, {"dnfoo": {"attrfoo1": ["valfoo1.3"]}})
    _test_helper_success_add(complex_db, {"dnfoo": {"attrfoo4": ["valfoo4.1"]}})
    _test_helper_success_add(complex_db, {"dnfoo": {"attrfoo10": ["valfoo10"]}}, attrlist=["*"])
    _test_helper_success_add(
        complex_db, {"dnfoo11": {"attrfoo11": ["valfoo11"]}}, attrlist=["attrfoo11"]
    )


def test_managed_replace_attr(complex_db):
    _test_helper_success(complex_db, {"dnfoo": {"attrfoo3": ["valfoo3.1"]}})
    _test_helper_success(complex_db, {"dnfoo": {"attrfoo12": ["valfoo12"]}}, attrlist=["*"])
    _test_helper_success(
        complex_db, {"dnfoo13": {"attrfoo13": ["valfoo13"]}}, attrlist=["attrfoo13"]
    )


def test_managed_simplereplace(complex_db):
    _test_helper_success(complex_db, {"dnfoo": {"attrfoo1": ["valfoo1.3"]}})


def test_managed_deleteattr(complex_db):
    _test_helper_success(complex_db, {"dnfoo": {"attrfoo1": []}})


def test_managed_deletenonexistattr(no_change_complex_db):
    _test_helper_nochange(no_change_complex_db, {"dnfoo": {"dummyattr": []}})


def test_managed_deleteentry(complex_db):
    _test_helper_success(complex_db, {"dnfoo": {}}, True)


def test_managed_deletenonexistentry(no_change_complex_db):
    _test_helper_nochange(no_change_complex_db, {"dummydn": {}}, True)


def test_managed_deletenonexistattrinnonexistentry(no_change_complex_db):
    _test_helper_nochange(no_change_complex_db, {"dummydn": {"dummyattr": []}})


def test_managed_add_attr_delete_others(complex_db):
    _test_helper_success(complex_db, {"dnfoo": {"dummyattr": ["dummyval"]}}, True)


def test_managed_no_net_change(no_change_complex_db):
    _test_helper_nochange(no_change_complex_db, {"dnfoo": {"attrfoo1": ["valfoo1.1", "valfoo1.2"]}})


def test_managed_repeated_values(db):
    _test_helper_success(db, {"dummydn": {"dummyattr": ["dummyval", "dummyval"]}})


# ---------------------------------------------------------------------------
# Tests for the wholesale-MOD_REPLACE + X-ORDERED idempotency fix.


@attr.s
class RecordingLdapDB(LdapDB):
    """LdapDB subclass that records the directives passed to dummy_change.

    Used to assert that ``replace:`` directives in the state actually reach the
    ldap3 backend as MOD_REPLACE ops instead of an add/delete diff -- which is
    what produces the ``TYPE_OR_VALUE_EXISTS`` failure against OpenLDAP
    cn=config (X-ORDERED) attributes.
    """

    change_calls = attr.ib(init=False, default=attr.Factory(list))

    def dummy_change(self, connect_spec, dn, before, after, replace_attrs=None):
        self.change_calls.append(
            {
                "dn": dn,
                "before": copy.deepcopy(before),
                "after": copy.deepcopy(after),
                "replace_attrs": set(replace_attrs or ()),
            }
        )
        return super().dummy_change(connect_spec, dn, before, after, replace_attrs=replace_attrs)


class TestReplaceAttrsAndXordered:
    """Override the module-level ``db`` fixture with a recording-capable one
    pre-populated with an X-ORDERED stored value, so the module-level
    ``configure_loader_modules`` fixture wires that into ``__salt__`` for us.
    """

    @pytest.fixture
    def db(self):
        rdb = RecordingLdapDB()
        rdb.db = {
            "olcDatabase={1}mdb,cn=config": {
                "olcSyncRepl": OrderedSet((b'{0}rid=001 provider="ldap://a"',)),
            },
        }
        return rdb

    def test_replace_directive_routes_through_replace_attrs(self, db):
        """A user ``replace:`` directive must reach ldap3.change in
        ``replace_attrs``, so the backend emits an atomic MOD_REPLACE rather
        than the MOD_ADD/MOD_DELETE diff that fails with TYPE_OR_VALUE_EXISTS
        against X-ORDERED attributes.
        """
        entries = [
            {
                "olcDatabase={1}mdb,cn=config": [
                    {
                        "replace": {
                            "olcSyncRepl": [
                                'rid=001 provider="ldap://a"',
                                'rid=002 provider="ldap://b"',
                            ]
                        }
                    }
                ]
            }
        ]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries)
        assert ret["result"] is True
        assert len(db.change_calls) == 1
        assert db.change_calls[0]["replace_attrs"] == {"olcSyncRepl"}

    def test_xordered_prefix_is_normalized_for_comparison(self, db):
        """When the server returned ``{N}``-prefixed values and the user
        supplied bare values, the state should consider the entry already in
        the desired state and emit no modify -- i.e. idempotent.
        """
        entries = [
            {
                "olcDatabase={1}mdb,cn=config": [
                    {"replace": {"olcSyncRepl": ['rid=001 provider="ldap://a"']}}
                ]
            }
        ]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries)
        assert ret["result"] is True
        assert not ret["changes"]
        assert not db.change_calls

    def test_xordered_normalization_is_opportunistic(self, db):
        """If the user supplies ``{N}``-prefixed values too, the stored copy
        is left alone, and any genuine difference still triggers a modify.
        """
        entries = [
            {
                "olcDatabase={1}mdb,cn=config": [
                    {"replace": {"olcSyncRepl": ['{0}rid=001 provider="ldap://different"']}}
                ]
            }
        ]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries)
        assert ret["result"] is True
        assert len(db.change_calls) == 1
        assert db.change_calls[0]["replace_attrs"] == {"olcSyncRepl"}


# ---------------------------------------------------------------------------
# Direct tests for module-level helpers. The X-ORDERED idempotency tests
# above exercise the bytes branch (slapd returns bytes); these cover the
# str branch and the directive-dispatch branches that the higher-level
# ``managed`` tests don't reach.


class TestXorderedPrefixHelpersStr:
    """Cover the str-input branches of ``_has_xordered_prefix`` and
    ``_strip_xordered_prefix``.
    """

    def test_has_xordered_prefix_str_true(self):
        assert saltext.ldap.states.ldap_mod._has_xordered_prefix("{0}foo") is True

    def test_has_xordered_prefix_str_false(self):
        assert saltext.ldap.states.ldap_mod._has_xordered_prefix("foo") is False

    def test_strip_xordered_prefix_str_present(self):
        assert saltext.ldap.states.ldap_mod._strip_xordered_prefix("{0}foo") == "foo"

    def test_strip_xordered_prefix_str_absent(self):
        assert saltext.ldap.states.ldap_mod._strip_xordered_prefix("foo") == "foo"


class TestUpdateEntryDirectives:
    """Direct tests for ``_update_entry`` covering directive branches not
    exercised by the higher-level ``managed`` tests.
    """

    @staticmethod
    def _status():
        return {
            "delete_others": False,
            "mentioned_attributes": set(),
            "replaced_attributes": set(),
        }

    def test_default_directive_applies_when_attr_absent(self):
        entry = {}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"default": {"foo": ["bar"]}})
        assert entry == {"foo": OrderedSet([to_bytes("bar")])}
        assert "foo" in status["mentioned_attributes"]

    def test_default_directive_skipped_when_attr_present(self):
        entry = {"foo": OrderedSet([to_bytes("existing")])}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"default": {"foo": ["bar"]}})
        assert entry == {"foo": OrderedSet([to_bytes("existing")])}

    def test_unknown_directive_raises(self):
        entry = {}
        status = self._status()
        with pytest.raises(ValueError, match="unknown directive: bogus"):
            saltext.ldap.states.ldap_mod._update_entry(entry, status, {"bogus": {"foo": ["bar"]}})

    def test_add_directive_with_empty_vals_and_no_existing_is_noop(self):
        entry = {}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"add": {"foo": []}})
        assert not entry

    def test_delete_directive_removes_specific_values(self):
        entry = {"foo": OrderedSet([to_bytes("a"), to_bytes("b")])}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"delete": {"foo": ["a"]}})
        assert entry == {"foo": OrderedSet([to_bytes("b")])}

    def test_delete_directive_with_empty_vals_removes_attr_entirely(self):
        entry = {"foo": OrderedSet([to_bytes("a")])}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"delete": {"foo": []}})
        assert not entry

    def test_delete_directive_removing_all_values_drops_attr(self):
        entry = {"foo": OrderedSet([to_bytes("a"), to_bytes("b")])}
        status = self._status()
        saltext.ldap.states.ldap_mod._update_entry(entry, status, {"delete": {"foo": ["a", "b"]}})
        assert not entry


class TestToset:
    """Direct tests for the ``_toset`` helper covering every type branch.

    The higher-level tests reach ``_toset`` only via list inputs of bytes
    values, so the None / str / int / TypeError-fallback branches need
    their own coverage.
    """

    def test_none(self):
        assert saltext.ldap.states.ldap_mod._toset(None) == OrderedSet()

    def test_str(self):
        assert saltext.ldap.states.ldap_mod._toset("foo") == OrderedSet([to_bytes("foo")])

    def test_int(self):
        assert saltext.ldap.states.ldap_mod._toset(42) == OrderedSet([to_bytes("42")])

    def test_float_falls_through_to_typeerror_branch(self):
        # Floats are neither None, str, nor int, and ``for x in 3.14``
        # raises TypeError, so the function falls through to the
        # str(thing) fallback. We only assert that the call doesn't
        # raise and produces an OrderedSet; the exact membership of the
        # fallback set is an implementation detail of the helper.
        result = saltext.ldap.states.ldap_mod._toset(3.14)
        assert isinstance(result, OrderedSet)

    def test_iterable_of_mixed_types(self):
        # ints inside an iterable get str()'d then bytes-encoded; bytes
        # pass through to_bytes() unchanged.
        result = saltext.ldap.states.ldap_mod._toset(["a", 1, b"b"])
        assert result == OrderedSet([to_bytes("a"), to_bytes("1"), to_bytes("b")])


class TestManagedTestMode:
    """Cover the ``__opts__['test'] is True`` dry-run branch in ``managed``.

    Overrides ``configure_loader_modules`` to set ``test: True`` so
    ``managed()`` reports the would-be changes without invoking the
    mutation backends.
    """

    @pytest.fixture
    def configure_loader_modules(self, db):
        salt_dunder = {
            "ldap3.connect": db.dummy_connect,
            "ldap3.search": db.dummy_search,
            "ldap3.add": db.dummy_add,
            "ldap3.delete": db.dummy_delete,
            "ldap3.change": db.dummy_change,
            "ldap3.modify": db.dummy_modify,
        }
        return {
            saltext.ldap.states.ldap_mod: {
                "__opts__": {"test": True},
                "__salt__": salt_dunder,
            }
        }

    def test_test_mode_does_not_apply_changes(self, complex_db):
        before = copy.deepcopy(complex_db.db)
        entries = [{"dnfoo": [{"replace": {"attrfoo1": ["newval"]}}]}]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries)
        assert ret["result"] is None
        assert ret["comment"] == "Would change LDAP entries"
        assert "dnfoo" in ret["changes"]
        # database must be untouched in test mode
        assert complex_db.db == before


class TestConnectSpecConnectionObject:
    """Cover the AttributeError branch in ``managed`` that handles a
    non-dict ``connect_spec`` (i.e. an already-built connection-like
    object).
    """

    def test_non_dict_connect_spec_skips_url_injection(self, db):
        # A list has no ``setdefault``; the AttributeError is caught and
        # treated as "already a connection object". The dummy_connect
        # ignores its argument, so managed() should complete normally.
        entries = [{"dn1": [{"add": {"foo": ["bar"]}}]}]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries, connect_spec=[])
        assert ret["result"] is True


@attr.s
class RaisingLdapDB(LdapDB):
    """LdapDB whose mutation methods raise ``LDAPError`` on demand so
    tests can exercise ``managed()``'s error-handling path.
    """

    raise_on_change = attr.ib(default=False)
    raise_on_add = attr.ib(default=False)
    raise_on_delete = attr.ib(default=False)

    def dummy_change(self, connect_spec, dn, before, after, replace_attrs=None):
        if self.raise_on_change:
            raise LDAPError("simulated change failure")
        return super().dummy_change(connect_spec, dn, before, after, replace_attrs=replace_attrs)

    def dummy_add(self, connect_spec, dn, attributes):
        if self.raise_on_add:
            raise LDAPError("simulated add failure")
        return super().dummy_add(connect_spec, dn, attributes)

    def dummy_delete(self, connect_spec, dn):
        if self.raise_on_delete:
            raise LDAPError("simulated delete failure")
        return super().dummy_delete(connect_spec, dn)


class TestLDAPErrorHandling:
    """Cover the ``except ldap3.LDAPError`` and error-reporting paths in
    ``managed()``.
    """

    @pytest.fixture
    def db(self):
        rdb = RaisingLdapDB(raise_on_change=True)
        rdb.db = {"dn1": {"foo": OrderedSet([b"existing"])}}
        return rdb

    def test_ldap_error_on_modify_is_reported(self, db):
        entries = [{"dn1": [{"replace": {"foo": ["new"]}}]}]
        ret = saltext.ldap.states.ldap_mod.managed("ldapi:///", entries)
        assert ret["result"] is False
        assert "failed to modify entry dn1" in ret["comment"]
        assert "simulated change failure" in ret["comment"]
