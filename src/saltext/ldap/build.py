# Copyright 2024 Broadcom Corporation
# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Build our python wheel.
"""
import contextlib
import logging
import os
import pathlib
import platform
import pprint
import shutil
import subprocess
import sys

import relenv.build
import relenv.buildenv
import relenv.common
import relenv.create
import relenv.fetch
import relenv.toolchain
from setuptools.build_meta import *

LDAP_VERSION = "2.5.18"
PYTHON_LDAP_PATCH = """diff --git a/setup.cfg b/setup.cfg
index fdb32fb..7fd19fb 100644
--- a/setup.cfg
+++ b/setup.cfg
@@ -17,7 +17,13 @@ license_file = LICENCE
 # These defines needs OpenLDAP built with
 # ./configure --with-cyrus-sasl --with-tls
 defines = HAVE_SASL HAVE_TLS
-
+library_dirs =
+	 /home/dan/src/saltext-ldap/build/gdb/lib
+	 /home/dan/src/saltext-ldap/build/gdb/lib/python3.10/site-packages/saltext/ldap/libldap/lib
+include_dirs =
+	 /home/dan/src/saltext-ldap/build/gdb/include
+	 /home/dan/src/saltext-ldap/build/gdb/lib/python3.10/site-packages/saltext/ldap/libldap/include
+libs = ldap lber ssl crypto sasl2
 extra_compile_args =
 extra_objects =

"""
_build_wheel = build_wheel


@contextlib.contextmanager
def pushd(path):
    """
    A pushd context manager.
    """
    orig = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(orig)


def build_gdb(prefix):
    """Compile and install gdb to the prefix."""
    root = pathlib.Path(os.environ.get("PWD", os.getcwd()))
    build = root / "build"

    src = build / "src"
    src.mkdir(exist_ok=True)

    os.environ.update(relenv.buildenv.buildenv(prefix))
    os.environ["CFLAGS"] = (
        f"{os.environ['CFLAGS']} -I{os.environ['RELENV_PATH']}/lib/python3.10/"
        f"site-packages/saltext/ldap/libldap/include"
    )
    os.environ["CPPFLAGS"] = (
        f"{os.environ['CPPFLAGS']} -I{os.environ['RELENV_PATH']}/lib/python3.10/"
        f"site-packages/saltext/ldap/libldap/include"
    )
    os.environ[
        "LDFLAGS"
    ] = f"{os.environ['LDFLAGS']} -L{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/libldap/lib"
    print(f"Build environment: {pprint.pformat(dict(os.environ))}")
    sys.stdout.flush()

    url = "https://github.com/cyrusimap/cyrus-sasl/releases/download/cyrus-sasl-2.1.28/cyrus-sasl-2.1.28.tar.gz"
    archive_name = str(src / pathlib.Path(url).name)
    dir_name = archive_name.split(".tar.gz")[0]

    if not pathlib.Path(dir_name).exists():
        relenv.common.download_url(
            url,
            src,
        )
        relenv.common.extract_archive(str(src), archive_name)
        with pushd(src / dir_name):
            subprocess.run(
                [
                    "./configure",
                    f"--prefix={os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/libldap",
                ],
                check=True,
            )
            subprocess.run(["make"], check=True)
            subprocess.run(["make", "install"], check=True)
    else:
        with pushd(src / dir_name):
            subprocess.run(["make", "install"], check=True)

    url = f"https://www.openldap.org/software/download/OpenLDAP/openldap-release/openldap-{LDAP_VERSION}.tgz"
    archive_name = str(src / pathlib.Path(url).name)
    dir_name = archive_name.split(".tgz")[0]

    if not pathlib.Path(dir_name).exists():
        relenv.common.download_url(
            url,
            src,
        )
        relenv.common.extract_archive(str(src), archive_name)
        with pushd(src / dir_name):
            subprocess.run(
                [
                    "./configure",
                    f"--prefix={os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/libldap",
                ],
                check=True,
            )
            subprocess.run(["make"], check=True)
            subprocess.run(["make", "install"], check=True)
    else:
        with pushd(src / dir_name):
            subprocess.run(["make", "install"], check=True)
    PYTHON_LDAP_VERSION = "3.4.4"

    url = f"https://github.com/python-ldap/python-ldap/archive/refs/tags/python-ldap-{PYTHON_LDAP_VERSION}.tar.gz"
    archive_name = src / pathlib.Path(url).name
    # github adds the python-ldap prefix for some reason.
    dir_name = "python-ldap-" + archive_name.name.split(".tar.gz")[0]
    if not pathlib.Path(dir_name).exists():
        relenv.common.download_url(
            url,
            src,
        )
        relenv.common.extract_archive(str(src), str(archive_name))
        with pushd(src / dir_name):
            with open("python-ldap.patch", "w") as fp:
                fp.write(PYTHON_LDAP_PATCH)
            subprocess.run(["patch", "-p", "1", "-i", "python-ldap.patch"], check=True)
        pip = build / "gdb" / "bin" / "pip3"
        env = os.environ.copy()
        env["RELENV_BUILDENV"] = 1
        subprocess.run([str(pip), "install", str(src / dir_name)], check=True)
    else:
        with pushd(src / dir_name):
            subprocess.run([str(pip), "install", str(src / dir_name)], check=True)
    vendored = pathlib.Path(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/vendored"
    )
    vendored.mkdir(exist_ok=True)
    (vendored / "__init__.py").touch()
    shutil.copytree(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/ldap",
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/vendored/ldap",
    )
    shutil.copy(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/ldapurl.py",
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/vendored/ldapurl.py",
    )
    shutil.copy(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/ldif.py",
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/vendored/ldif.py",
    )
    shutil.copy(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/_ldap.cpython-310-{platform.machine()}-linux-gnu.so",
        (
            f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/"
            f"saltext/ldap/vendored/_ldap.cpython-310-{platform.machine()}-linux-gnu.so"
        ),
    )
    relenv.relocate.main(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap",
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/libldap/lib",
        False,
    )
    shutil.copytree(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/libldap",
        "src/saltext/ldap/libldap",
    )
    shutil.copytree(
        f"{os.environ['RELENV_PATH']}/lib/python3.10/site-packages/saltext/ldap/vendored",
        "src/saltext/ldap/vendored",
    )


def build_wheel(wheel_directory, metadata_directory=None, config_settings=None):
    """PEP 517 wheel creation hook."""
    logging.basicConfig(level=logging.DEBUG)

    dirs = relenv.common.work_dirs()
    if not dirs.toolchain.exists():
        os.makedirs(dirs.toolchain)
    if not dirs.build.exists():
        os.makedirs(dirs.build)

    arch = relenv.common.build_arch()
    triplet = relenv.common.get_triplet(machine=arch)

    python = relenv.build.platform_versions()[0]
    version = relenv.common.__version__

    root = pathlib.Path(os.environ.get("PWD", os.getcwd()))
    build = root / "build"

    relenvdir = (build / "gdb").resolve()

    relenv.toolchain.fetch(arch, dirs.toolchain)
    relenv.fetch.fetch(version, triplet, python)
    if not relenvdir.exists():
        relenv.create.create(str(relenvdir), version=python)
    build_gdb(relenvdir)
    return _build_wheel(wheel_directory, metadata_directory, config_settings)
