import io
import os
import setuptools
import shutil
import tempfile

from lib.core.settings import VERSION


current_dir = os.path.abspath(os.path.dirname(__file__))
with io.open(os.path.join(current_dir, "README.md"), encoding="utf-8") as fd:
    desc = fd.read()

env_dir = tempfile.mkdtemp(prefix="dirsearch-install-")
shutil.copytree(os.path.abspath(os.getcwd()), os.path.join(env_dir, "dirsearch"))

os.chdir(env_dir)

setuptools.setup(
    name="dirsearch",
    version=VERSION,
    author="Mauro Soria",
    author_email="maurosoria@protonmail.com",
    description="Advanced web path scanner",
    long_description=desc,
    long_description_content_type="text/markdown",
    url="https://github.com/maurosoria/dirsearch",
    packages=setuptools.find_packages(),
    entry_points={"console_scripts": ["dirsearch=dirsearch.dirsearch:main"]},
    package_data={"dirsearch": ["*", "db/*"]},
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[
        "PySocks>=1.7.1",
        "Jinja2>=3.0.0",
        "defusedxml>=0.7.0",
        "pyopenssl>=21.0.0",
        "requests>=2.27.0",
        "requests_ntlm>=1.3.0",
        "colorama>=0.4.4",
        "ntlm_auth>=1.5.0",
        "beautifulsoup4>=4.8.0",
        "mysql-connector-python>=8.0.20",
        "psycopg[binary]>=3.0",
        "defusedcsv>=2.0.0",
        "requests-toolbelt>=1.0.0",
        "setuptools>=66.0.0",
        "httpx>=0.27.2",
        "httpx-ntlm>=1.4.0"
    ],
    classifiers=[
        "Programming Language :: Python",
        "Environment :: Console",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
        "Topic :: Security",
        "Programming Language :: Python :: 3.9",
    ],
    keywords=["infosec", "bug bounty", "pentesting", "security"],
)
