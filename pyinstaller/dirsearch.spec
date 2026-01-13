# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for dirsearch
Generates standalone executables for multiple platforms
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Get the project root directory
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Collect all submodules from lib
hidden_imports = collect_submodules('lib')

# Add required dependencies that might not be auto-detected
hidden_imports += [
    'requests',
    'httpx',
    'httpx._transports',
    'httpx._transports.default',
    'urllib3',
    'charset_normalizer',
    'certifi',
    'idna',
    'PySocks',
    'socks',
    'jinja2',
    'markupsafe',
    'defusedxml',
    'OpenSSL',
    'cryptography',
    'ntlm_auth',
    'requests_ntlm',
    'bs4',
    'beautifulsoup4',
    'colorama',
    'mysql.connector',
    'psycopg',
    'defusedcsv',
    'requests_toolbelt',
    'httpx_ntlm',
    'h11',
    'h2',
    'hpack',
    'hyperframe',
    'anyio',
    'sniffio',
    'httpcore',
    'socksio',
]

# Data files to include
datas = [
    (os.path.join(PROJECT_ROOT, 'db'), 'db'),
    (os.path.join(PROJECT_ROOT, 'config.ini'), '.'),
]

# Add static directory if it exists
static_dir = os.path.join(PROJECT_ROOT, 'static')
if os.path.exists(static_dir):
    datas.append((static_dir, 'static'))

# Jinja2 templates from lib/report
report_templates = os.path.join(PROJECT_ROOT, 'lib', 'report')
if os.path.exists(report_templates):
    datas.append((report_templates, 'lib/report'))

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'dirsearch.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'test',
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dirsearch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
