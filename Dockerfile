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
    any2fasta \
    git \
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

ARG ABRICATE_REPRODUCIBLE_COMMIT=ab166ca55031f8f63fc71ff597df206d3ee7f093

RUN git clone https://github.com/IRCGP-Lab/abricate_reproducible.git /tmp/abricate_reproducible \
    && git -C /tmp/abricate_reproducible checkout "${ABRICATE_REPRODUCIBLE_COMMIT}" \
    && mv /tmp/abricate_reproducible /app/EcoML-VP/abricate_reproducible \
    && rm -rf /app/EcoML-VP/abricate_reproducible/.git

ENV ECOML_VP_DIR=/app/EcoML-VP
ENV INPUT_DIR=/input
ENV AGENT_LOG_PATH=/app/logs/agent.jsonl
RUN mkdir -p /input /app/logs

CMD ["conda", "run", "--no-capture-output", "-n", "ecoml", "python", "-u", "agent.py"]
