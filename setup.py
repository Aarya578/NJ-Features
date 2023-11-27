from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in nj_features/__init__.py
from nj_features import __version__ as version

setup(
	name="nj_features",
	version=version,
	description="Moving all custom developed apps to this app. Development from 28th Oct 2023 will be available in this app",
	author="NewJaisa - IT Team",
	author_email="itsupport@newjaisa.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
