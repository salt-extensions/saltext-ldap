#!/bin/sh
# Used by github actions to build wheels in a CI/CD container.
apt-get update;
apt-get install -y gcc python3 \
   python3-pip python3-venv build-essential patchelf m4 texinfo groff-base
cd /src
python3 -m venv venv
venv/bin/pip install build wheel setuptools
venv/bin/python3 -m build
