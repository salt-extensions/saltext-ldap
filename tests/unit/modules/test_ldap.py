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


# 'search' function tests: 1


def test_search():
    """
    Test if it run an arbitrary LDAP query and return the results.
    """

    class MockConnect:
        """
        Mocking _connect method
        """

        def __init__(self):
            self.bdn = None
            self.scope = None
            self._filter = None
            self.attrs = None

        def search_s(self, bdn, scope, _filter, attrs):
            """
            Mock function for search_s
            """
            self.bdn = bdn
            self.scope = scope
            self._filter = _filter
            self.attrs = attrs
            return "SALT"

    mock = MagicMock(return_value=True)
    with patch.dict(ldap_mod.__salt__, {"config.option": mock}):
        with patch.object(ldap_mod, "_connect", MagicMock(return_value=MockConnect())):
            with patch.object(time, "time", MagicMock(return_value=8e-04)):
                assert ldap_mod.search(filter="myhost") == {
                    "count": 4,
                    "results": "SALT",
                    "time": {"raw": "0.0", "human": "0.0ms"},
                }
