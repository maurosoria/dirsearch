import io
import os
import setuptools
import shutil
import tempfile

from lib.core.installation import get_dependencies
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
    python_requires=">=3.7",
    install_requires=get_dependencies(),
    classifiers=[
        "Programming Language :: Python",
        "Environment :: Console",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
        "Topic :: Security",
        "Programming Language :: Python :: 3.7",
    ],
    keywords=["infosec", "bug bounty", "pentesting", "security"],
)
