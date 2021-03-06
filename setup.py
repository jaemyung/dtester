from setuptools import setup, find_packages

setup(
    name    = "dtester",
    version = "0.2.dev0",
    description = "A component based test suite for distributed systems",
    author = "Markus Wanner",
    author_email = "markus@bluegap.ch",
    url = "http://www.bluegap.ch/projects/dtester",
    license = "Boost Software License v1.0 (BSD like)",
    packages = find_packages(),
    install_requires = ["Twisted >= 2.4.0", "setuptools"],

    test_suite = "dtester.tests.test_all",

    entry_points = {
        "distutils.commands": [
            "dtest = dtester.setuptools_dtester:dtest"
            ],
        }
)
