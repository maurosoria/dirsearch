import setuptools
import os
import tempfile
import shutil

env_dir = tempfile.mkdtemp(prefix='dirsearch-install-')
shutil.copytree(os.path.abspath(os.getcwd()),
                os.path.join(env_dir, "dirsearch"))
print("Created setup.py env in {}".format(env_dir))

os.chdir(env_dir)

print(setuptools.find_packages())
setuptools.setup(
    name="dirsearch",
    version="0.4.1",
    author="Mauro Soria",
    author_email="maurosoria@protonmail.com",
    description="Advanced web path scanner",
    url="https://github.com/maurosoria/dirsearch",

    packages=setuptools.find_packages(),
    entry_points={
        "console_scripts": ["dirsearch=dirsearch.dirsearch:Program"]
    },

    package_data={
        "dirsearch": ["*", "db/*"]
    },
    include_package_data=True,

    python_requires=">=3.7",
    install_requires=["certifi>=2020.11.8", "chardet>=3.0.2", "urllib3>=1.21.1", "cryptography>=2.8", "PySocks>=1.6.8", "cffi>=1.14.0"],

    classifiers=[
        "Programming Language :: Python",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License",
        "Operating System :: OS Independent",
        "Topic :: Security"
    ]
)

shutil.rmtree(env_dir, ignore_errors=True)
