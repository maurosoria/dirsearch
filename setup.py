from setuptools import setup

import sys
if sys.version_info < (2,7):
    sys.exit('Sorry, Python < 2.7 is not supported')

setup(name='dirsearch',
      version='0.1',
      description='dirsearch is a simple command line tool designed to brute force directories and files in websites.',
      url='https://github.com/maurosoria/dirsearch',
      author='maurosoria',
      author_email='maurosoria@gmail.com',
      license='GNU',
      scripts=['dirsearch.py'],
      entry_points = {
        'console_scripts': ['dirsearch=dirsearch:main'],
      },
      zip_safe=False)
