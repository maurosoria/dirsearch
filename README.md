dirsearch
=========

Current Release: v0.3.8 (2017.07.25)


Overview
--------
dirsearch is a simple command line tool designed to brute force directories and files in websites.


Operating Systems supported
---------------------------
- Windows XP/7/8/10
- GNU/Linux
- MacOSX

Features
--------
- Multithreaded
- Keep alive connections
- Support for multiple extensions (-e|--extensions asp,php)
- Reporting (plain text, JSON)
- Heuristically detects invalid web pages
- Recursive brute forcing
- HTTP proxy support
- User agent randomization
- Batch processing
- Request delaying

About wordlists
---------------
Dictionaries must be text files. Each line will be processed as such, except that the special word %EXT% is used, which will generate one entry for each extension (-e | --extension) passed as an argument.

Example:
- example/
- example.%EXT%

Passing the extensions "asp" and "aspx" will generate the following dictionary:
- example/
- example.asp
- example.aspx

You can also use -f | --force-extensions switch to append extensions to every word in the wordlists (like DirBuster).

## Support Docker
### Install Docker Linux
Install Docker
```sh
curl -fsSL https://get.docker.com | bash
```
> To use docker you need superuser power

### Build Image dirsearch
To create image
```sh
docker build -t "dirsearch:v0.3.8" .
```
> **dirsearch** this is name the image and **v0.3.8** is version

### Using dirsearch
For using
```sh
docker run -it --rm "dirsearch:v0.3.8" -u target -e php,html,png,js,jpg
```
> target is the site or IP

License
-------
Copyright (C) Mauro Soria (maurosoria at gmail dot com)

License: GNU General Public License, version 2


Contributors
---------
Special thanks for these people.

- Damian89
- Bo0oM
- liamosaur
- redshark1802
- SUHAR1K
- FireFart
- k2l8m11n2
- vlohacks
- r0p0s3c
