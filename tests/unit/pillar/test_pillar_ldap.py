import salt.utils.stringutils

from saltext.ldap.pillar import pillar_ldap


def test__config_returns_str():
    conf = {"foo": "bar"}
    assert pillar_ldap._config("foo", conf) == salt.utils.stringutils.to_str("bar")


def test__conf_defaults_to_none():
    conf = {"foo": "bar"}
    assert pillar_ldap._config("bang", conf) is None


def test__conf_returns_str_from_unicode_default():
    conf = {"foo": "bar"}
    default = salt.utils.stringutils.to_unicode("bam")
    assert pillar_ldap._config("bang", conf, default) == salt.utils.stringutils.to_str("bam")
