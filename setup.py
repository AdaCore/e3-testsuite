from setuptools import setup, find_packages

import os

install_requires = ["e3-core"]

# Get e3 version from the VERSION file.
version_file = os.path.join(os.path.dirname(__file__), "VERSION")
with open(version_file) as f:
    version = f.read().strip()

with open(os.path.join(os.path.dirname(__file__), "README.md")) as f:
    long_description = f.read()

setup(
    name="e3-testsuite",
    version=version,
    description="E3 testsuite",
    license="GPLv3",
    author="AdaCore",
    author_email="info@adacore.com",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3.7",
        "Topic :: Software Development :: Build Tools",
    ],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=install_requires,
    namespace_packages=["e3"],
    entry_points={"console_scripts": ["e3-test = e3.testsuite.main:main"]},
)
