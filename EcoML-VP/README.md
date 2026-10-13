# EcoML-VP

A machine learning pipeline that uses Random Forest to predict pathogenicity levels (EpiHR, non-EpiHR, Pathotype-negative) of _Escherichia coli_ from genomic data using BLAST and abricate analysis.

## Installation

```bash
# Create a new conda environment (recommended)
conda create -n ecoml-vp python=3.9
conda activate ecoml-vp

# Clone the repository
git clone https://github.com/IRCGP-Lab/EcoML-VP.git
cd EcoML-VP
```

### Install all dependencies

```bash
bash install.sh
```

### Using pip

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install BLAST and abricate
conda install -c bioconda blast abricate
```

## Usage

### Command Line Interface

```bash
# Basic usage
ecoml-vp input.fasta

# Or using python directly
python main.py input.fasta
```

### Example

```bash
# Predict pathogenicity for a sample
ecoml-vp testfiles/CMCEC0923.fasta
# Output: EpiHR, non-EpiHR, or Pathotype-negative
```

## Input Format

The pipeline expects a FASTA file containing genomic sequences for analysis.

## Output

The pipeline outputs one of three pathogenicity levels:
- **EpiHR**: Epidemiologically defined high-risk
- **non-EpiHR**: Pathogenic isolates not meeting the EpiHR criteria
- **Pathotype-negative**: Isolates lacking WGS-detected pathotype-defining virulence genes

## Dependencies

- Python >= 3.7
- pandas
- scikit-learn
- BLAST+ (blastn)
- abricate

## Files

- `main.py`: Main pipeline script
- `final_RF.pkl`: Trained Random Forest model
- `train_df.csv` : Data used for training
- `test_df.csv`: Reference dataframe for feature columns
- `ecoli/e.coli_pathotype.fa`: BLAST database
- `abricate_reproducible/`: Abricate tools and databases

## Citation

If you use this pipeline in your research, please cite:

```
[Paper citation]
```

## License

GNU General Public License v3.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
