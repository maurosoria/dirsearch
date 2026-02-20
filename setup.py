import io
import os
import shutil
import tempfile

import pkg_resources
import setuptools

from lib.core.settings import VERSION

current_dir = os.path.abspath(os.path.dirname(__file__))
with io.open(os.path.join(current_dir, "README.md"), encoding="utf-8") as fd:
    desc = fd.read()

# Source - https://stackoverflow.com/questions/49689880/proper-way-to-parse-requirements-file-after-pip-upgrade-to-pip-10-x-x
# Posted by sinoroc, modified by community. See post 'Timeline' for change history
# Retrieved 2026-01-23, License - CC BY-SA 4.0

with io.open(os.path.join(current_dir, "requirements.txt"), encoding="utf-8") as requirements_txt:
    install_requires = [
        str(requirement)
        for requirement 
        in pkg_resources.parse_requirements(requirements_txt)
    ]

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
    install_requires=install_requires,
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
