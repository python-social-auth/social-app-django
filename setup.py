# -*- coding: utf-8 -*-
"""Setup file for easy installation"""
import re

from os.path import join, dirname
from setuptools import setup, find_packages


VERSION_RE = re.compile('__version__ = \'([\d\.]+)\'')


def read_version():
    with open('social_django/__init__.py') as file:
        version_line = [line for line in file.readlines()
                        if line.startswith('__version__')][0]
        return VERSION_RE.match(version_line).groups()[0]


def long_description():
    return open(join(dirname(__file__), 'README.md')).read()


def load_requirements():
    return open(join(dirname(__file__), 'requirements.txt')).readlines()

setup(
    name='compliant-social-app-django',
    version=read_version(),
    author='Rightly',
    author_email='',
    description='Python Social Authentication, Django integration, Google compliant fork',
    license='BSD',
    keywords='django, social auth',
    url='https://github.com/RightlyGroup/compliant-social-app-django',
    packages=find_packages(),
    long_description=long_description(),
    long_description_content_type='text/markdown',
    install_requires=load_requirements(),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Topic :: Internet',
        'License :: OSI Approved :: BSD License',
        'Intended Audience :: Developers',
        'Environment :: Web Environment',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3'
    ],
    zip_safe=False
)
