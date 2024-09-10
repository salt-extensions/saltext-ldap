# Copyright 2024 Broadcom Corporation
# Copyright 2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
import importlib
import sys

__version__ = "0.0.2"

USE_VENDORED_LDAP = True


class SaltextLdapImporter:
    """
    Handle runtime wrapping of module methods.
    """

    def find_module(self, module_name, package_path=None):
        """
        Determine if the requested module matches one of our vendored modules.
        """
        if USE_VENDORED_LDAP:
            if (
                module_name.startswith("ldap")
                or module_name.startswith("_ldap")
                or module_name.startswith("ldif")
                or module_name.startswith("ldapurl")
            ):
                return self
        return None

    def load_module(self, name):
        """
        Load our vendored module instead of the one requested.
        """
        mod = importlib.import_module("saltext.ldap.vendored.{}".format(name))
        sys.modules[name] = mod
        return mod

    def create_module(self, spec):
        """
        Perform the load_module call.
        """
        return self.load_module(spec.name)

    def exec_module(self, module):
        """
        No-op method for compatability.
        """
        return None


sys.meta_path = [SaltextLdapImporter()] + sys.meta_path
