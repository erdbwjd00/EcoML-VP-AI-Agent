#!/bin/bash

# Installer for EcoML-VP dependencies

set -e

# Check for conda
if ! command -v conda &> /dev/null; then
    echo "conda could not be found. Please install Miniconda or Anaconda first." >&2
    exit 1
fi

echo "Installing BLAST and abricate via conda..."
conda install -y -c bioconda blast abricate

echo "Installing Perl dependencies via conda..."
conda install -y -c bioconda perl-path-tiny perl-list-moreutils

echo "Installing Python dependencies via pip..."
pip install -r requirements.txt

echo "Cloning abricate_reproducible repository..."
if [ -d "abricate_reproducible" ]; then
    echo "abricate_reproducible directory already exists. Removing and re-cloning..."
    rm -rf abricate_reproducible
fi
git clone git@github.com:IRCGP-Lab/abricate_reproducible.git

echo "Setting up abricate databases..."
./abricate_reproducible/bin/abricate --setupdb

echo "All dependencies installed successfully!"
