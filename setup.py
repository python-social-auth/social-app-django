"""Setup file for easy installation"""
import re
from os.path import dirname, join

from setuptools import setup

VERSION_RE = re.compile(r"__version__ = \"([\d\.]+)\"")


def read_version():
    with open("social_django/__init__.py") as file:
        version_line = [
            line for line in file.readlines() if line.startswith("__version__")
        ][0]
        return VERSION_RE.match(version_line).groups()[0]


def long_description():
    return open(join(dirname(__file__), "README.md")).read()


def load_requirements():
    return open(join(dirname(__file__), "requirements.txt")).readlines()


setup(
    name="social-auth-app-django",
    version=read_version(),
    author="Matias Aguirre",
    author_email="matiasaguirre@gmail.com",
    description="Python Social Authentication, Django integration.",
    license="BSD",
    keywords="django, social auth",
    url="https://github.com/python-social-auth/social-app-django",
    packages=[
        "social_django",
        "social_django.migrations",
        "social_django.management",
        "social_django.management.commands",
    ],
    long_description=long_description(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    install_requires=load_requirements(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Topic :: Internet",
        "License :: OSI Approved :: BSD License",
        "Intended Audience :: Developers",
        "Environment :: Web Environment",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    zip_safe=False,
)
