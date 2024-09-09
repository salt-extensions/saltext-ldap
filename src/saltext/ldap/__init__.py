# Copyright 2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
import sys
import importlib

__version__ = "0.0.1"

USE_VENDORED_LDAP=True

class SaltextLdapImporter:
    """
    Handle runtime wrapping of module methods.
    """

    def find_module(self, module_name, package_path=None):
        if USE_VENDORED_LDAP:
            if module_name.startswith("ldap") or module_name.startswith("_ldap") or module_name.startswith('ldif') or module_name.startswith("ldapurl"):
                return self
        return None

    def load_module(self, name):
        mod = importlib.import_module("saltext.ldap.vendored.{}".format(name))
        sys.modules[name] = mod
        return mod

    def create_module(self, spec):
        return self.load_module(spec.name)

    def exec_module(self, module):
        return None

sys.meta_path = [SaltextLdapImporter()] + sys.meta_path
