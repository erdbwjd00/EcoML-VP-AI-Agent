FROM python:3.11-slim

WORKDIR /app

COPY requirements-agent.txt .
RUN pip install --no-cache-dir -r requirements-agent.txt

COPY agent.py .
COPY EcoML-VP/ ./EcoML-VP/

ENV ECOML_VP_DIR=/app/EcoML-VP

CMD ["python", "-u", "agent.py"]
