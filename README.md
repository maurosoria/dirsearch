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

How to use
---------------

Some examples how to use dirsearch - those are the most common arguments. If you need all, just use the "-h" argument.
```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --recursive -R 2
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --recursive -R 4 --scan-subdirs=/,/wp-content/,/wp-admin/
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --exclude-texts=This,AndThat
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -H "User-Agent: IE"
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt -t 20
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --random-agents
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --json-report=reports/target.json
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --simple-report=reports/target-paths.txt
```

```
python3 dirsearch.py -e php,txt,zip -u https://target -w db/dicc.txt --plain-text-report=reports/target-paths-and-status.json
```

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
