from unittest.mock import MagicMock

import jinja2
import pytest
import salt.utils.stringutils
from salt.exceptions import SaltInvocationError

from saltext.ldap.pillar import ldap_mod


@pytest.fixture
def configure_loader_modules():
    return {ldap_mod: {"__grains__": {"id": "minion-1"}, "__salt__": {}}}


# ---------------------------------------------------------------------------
# _config
# ---------------------------------------------------------------------------


def test__config_returns_str():
    conf = {"foo": "bar"}
    assert ldap_mod._config("foo", conf) == salt.utils.stringutils.to_str("bar")


def test__conf_defaults_to_none():
    conf = {"foo": "bar"}
    assert ldap_mod._config("bang", conf) is None


def test__conf_returns_str_from_unicode_default():
    conf = {"foo": "bar"}
    default = salt.utils.stringutils.to_unicode("bam")
    assert ldap_mod._config("bang", conf, default) == salt.utils.stringutils.to_str("bam")


def test__config_decodes_bytes_values():
    """Values stored as bytes in conf must come back as str."""
    conf = {"server": b"ldap.example.com"}
    result = ldap_mod._config("server", conf)
    assert result == "ldap.example.com"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _render_template
# ---------------------------------------------------------------------------


def test__render_template_substitutes_grains(tmp_path):
    """Template should have access to __grains__ at render time."""
    template = tmp_path / "pillar.yaml.j2"
    template.write_text("minion_id: {{ id }}\n")
    rendered = ldap_mod._render_template(str(template))
    # jinja2 strips the trailing newline from templates by default
    assert rendered == "minion_id: minion-1"


def test__render_template_raises_when_missing(tmp_path):
    """A missing template file should surface jinja2's TemplateNotFound."""
    with pytest.raises(jinja2.exceptions.TemplateNotFound):
        ldap_mod._render_template(str(tmp_path / "does-not-exist.yaml"))


# ---------------------------------------------------------------------------
# _result_to_dict (mode: map)
# ---------------------------------------------------------------------------


def test__result_to_dict_map_mode_collects_attrs_and_lists():
    conf = {
        "mode": "map",
        "attrs": ["cn", "displayName", "dn"],
        "lists": ["memberOf"],
    }
    result = [
        (
            "cn=johndoe,ou=users,dc=example,dc=com",
            {
                "cn": ["johndoe"],
                "displayName": ["John Doe"],
                "memberOf": ["cn=admins", "cn=ops"],
                "ignored": ["never-returned"],
            },
        ),
    ]
    data = ldap_mod._result_to_dict({}, result, conf, "users")
    assert data == {
        "users": [
            {
                "dn": "cn=johndoe,ou=users,dc=example,dc=com",
                "cn": "johndoe",
                "displayName": "John Doe",
                "memberOf": ["cn=admins", "cn=ops"],
            },
        ],
    }


# ---------------------------------------------------------------------------
# _result_to_dict (mode: dict)
# ---------------------------------------------------------------------------


def test__result_to_dict_dict_mode_keyed_by_dn():
    """With the default dict_key_attr ('dn'), records are keyed by their DN."""
    conf = {"mode": "dict", "attrs": ["cn", "dn"], "lists": ["memberOf"]}
    result = [
        (
            "cn=alice,dc=example,dc=com",
            {"cn": ["alice"], "memberOf": ["cn=admins"]},
        ),
        (
            "cn=bob,dc=example,dc=com",
            {"cn": ["bob"], "memberOf": ["cn=users"]},
        ),
    ]
    data = ldap_mod._result_to_dict({}, result, conf, "people")
    assert data == {
        "people": {
            "cn=alice,dc=example,dc=com": [
                {"dn": "cn=alice,dc=example,dc=com", "cn": "alice", "memberOf": ["cn=admins"]},
            ],
            "cn=bob,dc=example,dc=com": [
                {"dn": "cn=bob,dc=example,dc=com", "cn": "bob", "memberOf": ["cn=users"]},
            ],
        },
    }


def test__result_to_dict_dict_mode_groups_by_custom_key():
    """An explicit dict_key_attr groups entries sharing that attribute value."""
    conf = {
        "mode": "dict",
        "dict_key_attr": "department",
        "attrs": ["cn", "department"],
    }
    result = [
        ("cn=alice,dc=x", {"cn": ["alice"], "department": ["eng"]}),
        ("cn=bob,dc=x", {"cn": ["bob"], "department": ["eng"]}),
        ("cn=carol,dc=x", {"cn": ["carol"], "department": ["sales"]}),
    ]
    data = ldap_mod._result_to_dict({}, result, conf, "by_dept")
    assert set(data["by_dept"].keys()) == {"eng", "sales"}
    assert len(data["by_dept"]["eng"]) == 2
    assert len(data["by_dept"]["sales"]) == 1
    assert {entry["cn"] for entry in data["by_dept"]["eng"]} == {"alice", "bob"}


# ---------------------------------------------------------------------------
# _do_search
# ---------------------------------------------------------------------------


def test__do_search_requires_filter():
    """Missing filter is a configuration mistake and must raise."""
    with pytest.raises(SaltInvocationError, match="missing filter"):
        ldap_mod._do_search({"server": "ldap.example.com"})


def test__do_search_invokes_ldap_search_with_built_args():
    """_do_search should forward filter/dn/scope/attrs and connargs to ldap.search."""
    search = MagicMock(return_value={"results": [("cn=a,dc=x", {"cn": ["a"]})]})
    conf = {
        "server": "ldap.example.com",
        "port": 636,
        "tls": True,
        "binddn": "cn=svc,dc=x",
        "bindpw": "secret",
        "filter": "(objectClass=user)",
        "dn": "dc=example,dc=com",
        "scope": 2,
        "attrs": ["cn"],
        "lists": ["memberOf"],
    }
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(ldap_mod.__salt__, "ldap.search", search)
        result = ldap_mod._do_search(conf)
    assert result == [("cn=a,dc=x", {"cn": ["a"]})]
    search.assert_called_once()
    args, kwargs = search.call_args
    # positional: filter, dn, scope, attrs
    assert args[0] == "(objectClass=user)"
    assert args[1] == "dc=example,dc=com"
    assert args[2] == 2
    assert sorted(args[3]) == sorted(["cn", "memberOf", "dn"])
    # binddn+bindpw should force anonymous to False even if the conf didn't say so
    assert kwargs["anonymous"] is False
    assert kwargs["binddn"] == "cn=svc,dc=x"
    assert kwargs["server"] == "ldap.example.com"


def test__do_search_returns_empty_on_ldap_error(caplog):
    """ldap.search raising should be swallowed with a critical log and return {}."""
    search = MagicMock(side_effect=RuntimeError("boom"))
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(ldap_mod.__salt__, "ldap.search", search)
        assert ldap_mod._do_search({"filter": "(cn=*)"}) == {}


# ---------------------------------------------------------------------------
# ext_pillar
# ---------------------------------------------------------------------------


def test_ext_pillar_returns_empty_when_config_missing(tmp_path, caplog):
    """A nonexistent config file is logged at debug and returns {} (no crash)."""
    missing = tmp_path / "nope.yaml"
    assert ldap_mod.ext_pillar("minion-1", {}, str(missing)) == {}


def test_ext_pillar_returns_empty_for_non_dict_yaml(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("- just\n- a\n- list\n")
    assert ldap_mod.ext_pillar("minion-1", {}, str(cfg)) == {}


def test_ext_pillar_returns_empty_when_search_order_missing(tmp_path):
    cfg = tmp_path / "noorder.yaml"
    cfg.write_text("source1:\n  filter: '(cn=*)'\n")
    assert ldap_mod.ext_pillar("minion-1", {}, str(cfg)) == {}


def test_ext_pillar_returns_empty_on_yaml_parse_error(tmp_path):
    cfg = tmp_path / "broken.yaml"
    # Unbalanced YAML mapping triggers a YAMLError, not just a falsy value
    cfg.write_text("source1:\n  filter: '(cn=*)\n  bad: : :\n")
    assert ldap_mod.ext_pillar("minion-1", {}, str(cfg)) == {}


def test_ext_pillar_aggregates_results_in_search_order(tmp_path):
    """Each source's results are funneled through _result_to_dict and merged."""
    cfg = tmp_path / "good.yaml"
    cfg.write_text(
        "users:\n"
        "  filter: '(objectClass=user)'\n"
        "  mode: map\n"
        "  attrs: ['cn']\n"
        "search_order:\n"
        "  - users\n"
    )
    search = MagicMock(
        return_value={
            "results": [("cn=alice,dc=x", {"cn": ["alice"]})],
        },
    )
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(ldap_mod.__salt__, "ldap.search", search)
        data = ldap_mod.ext_pillar("minion-1", {}, str(cfg))
    assert data == {"users": [{"cn": "alice"}]}
    search.assert_called_once()


def test_ext_pillar_renders_jinja_with_grains(tmp_path):
    """The config file is jinja-rendered with __grains__ before YAML parsing."""
    cfg = tmp_path / "templated.yaml"
    cfg.write_text(
        "u_{{ id }}:\n"
        "  filter: '(uid={{ id }})'\n"
        "  mode: map\n"
        "  attrs: ['cn']\n"
        "search_order:\n"
        "  - u_{{ id }}\n"
    )
    search = MagicMock(return_value={"results": [("cn=minion-1,dc=x", {"cn": ["minion-1"]})]})
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(ldap_mod.__salt__, "ldap.search", search)
        data = ldap_mod.ext_pillar("minion-1", {}, str(cfg))
    assert data == {"u_minion-1": [{"cn": "minion-1"}]}
    # Filter passed to ldap.search should also have been rendered
    assert search.call_args.args[0] == "(uid=minion-1)"


def test_ext_pillar_skips_sources_with_no_results(tmp_path):
    """A source returning {} should not contribute keys to the final data."""
    cfg = tmp_path / "two.yaml"
    cfg.write_text(
        "empty:\n"
        "  filter: '(cn=missing)'\n"
        "  mode: map\n"
        "  attrs: ['cn']\n"
        "good:\n"
        "  filter: '(cn=alice)'\n"
        "  mode: map\n"
        "  attrs: ['cn']\n"
        "search_order:\n"
        "  - empty\n"
        "  - good\n"
    )
    side_effect = [
        {"results": []},  # _do_search → [] which is falsy → skipped
        {"results": [("cn=alice,dc=x", {"cn": ["alice"]})]},
    ]
    search = MagicMock(side_effect=side_effect)
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(ldap_mod.__salt__, "ldap.search", search)
        data = ldap_mod.ext_pillar("minion-1", {}, str(cfg))
    assert data == {"good": [{"cn": "alice"}]}
    assert search.call_count == 2
