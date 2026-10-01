FROM continuumio/miniconda3:latest

WORKDIR /app

RUN conda create -y \
    -n ecoml \
    python=3.9 \
    && conda clean -afy

SHELL ["conda", "run", "-n", "ecoml", "/bin/bash", "-c"]

RUN conda install -y \
    -c conda-forge \
    -c bioconda \
    blast \
    abricate \
    perl-path-tiny \
    perl-list-moreutils \
    && conda clean -afy

RUN abricate --setupdb

COPY EcoML-VP/requirements.txt /tmp/ecoml-requirements.txt

RUN pip install --no-cache-dir \
    -r /tmp/ecoml-requirements.txt

COPY requirements-agent.txt .

RUN pip install --no-cache-dir \
    -r requirements-agent.txt

COPY agent.py .
COPY EcoML-VP/ ./EcoML-VP/

ENV ECOML_VP_DIR=/app/EcoML-VP
ENV QWEN_BASE_URL=http://qwen-server:8080/v1

CMD ["conda", "run", "--no-capture-output", "-n", "ecoml", "python", "-u", "agent.py"]
