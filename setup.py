import os
import re

from codecs import open as copen  # to use a consistent encoding
from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))

# get the long description from the relevant file
with copen(os.path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()


def read(*parts):
    with copen(os.path.join(here, *parts), 'r') as fp:
        return fp.read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError('Unable to find version string.')


__version__ = find_version('kg_covid_19', '__version__.py')

test_deps = [
    'pytest',
    'pytest-cov',
    'coveralls',
    'validate_version_code',
    'codacy-coverage',
    'parameterized'
]

extras = {
    'test': test_deps,
}

setup(
    name='kg_covid_19',
    version=__version__,
    description='KG hub for emerging viruses',
    long_description=long_description,
    url='https://github.com/justaddcoffee/kg-emerging-viruses',
    author='justaddcoffee+github@gmail.com',
    author_email='Justin Reese',
    python_requires='>=3.7',

    # choose your license
    license='BSD-3',
    include_package_data=True,
    classifiers=[
        'Development Status :: 3 - Beta',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3'
    ],
    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    tests_require=test_deps,

    # add package dependencies
    install_requires=[
        'tqdm',
        'tabula-py',
        'obonet',
        'wget',
        'compress_json',
        'click',
        'pyyaml',
        'bmt',
        'SPARQLWrapper',
        'ensmallen_graph==0.4.3',
        'kgx==0.3.1'
    ],
    extras_require=extras,
)
