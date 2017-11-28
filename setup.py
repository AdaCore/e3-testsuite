from setuptools import setup, find_packages
from datetime import datetime

version = '20.08.' + datetime.utcnow().strftime('%Y%m%d')
install_requires = [
    'e3-core']

setup(
    name='e3-testsuite',
    version=version,
    description="E3 testsuite",
    author="AdaCore's Production Team",
    packages=find_packages(),
    install_requires=install_requires,
    namespace_packages=['e3'],
    use_2to3=True,
    entry_points={
        'console_scripts': [
            'e3-test = e3.testsuite.main:main'
    ]})
