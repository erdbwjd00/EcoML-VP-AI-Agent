from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="ecoml-vp",
    version="1.0.0",
    author="Yoojung Hwang",
    author_email="hwangyoojung1213@gmail.com",
    description="EcoML-VP: Machine learning prediction pipeline for E. coli pathogenicity assessment",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/IRCGP-Lab/EcoML-VP",
    packages=find_packages(),
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
    python_requires=">=3.7",
    install_requires=requirements,
    py_modules=["main"],
    entry_points={
        "console_scripts": [
            "ecoml-vp = main:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.pkl", "*.csv", "*.fa", "*.fa.*"],
    },
)
