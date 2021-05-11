import setuptools

setuptools.setup(
    name="dirsearch",
    version="0.4.1",
    author="Mauro Soria",
    author_email="maurosoria@protonmail.com",
    description="Advanced web path scanner",
    url="https://github.com/maurosoria/dirsearch",
    packages=setuptools.find_packages(),
    py_modules=["dirsearch"],
    package_dir={"dirsearch": "../dirsearch"},
    entry_points={
        "console_scripts": ["dirsearch=dirsearch:Program"]
    },
    package_data={"": ["../default.conf", "../lib/controller/banner.txt", "../db/*"]},
    include_package_data=True,
    python_requires=">=3.0",
    install_requires=["certifi>=2020.11.8", "chardet>=3.0.2", "urllib3>=1.21.1", "cryptography>=2.8", "PySocks"],
    classifiers=[
        "Programming Language :: Python",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License",
        "Operating System :: OS Independent",
        "Topic :: Security"
    ],
)
