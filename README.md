# EcoML-VP AI Agent

A tool-calling AI agent that analyzes *E. coli* genome FASTA files with the EcoML-VP pipeline, included in this repository, driven by natural-language requests.

The agent talks to **any OpenAI-compatible LLM server that supports tool (function) calling**, so you can bring your own model and inference backend (llama.cpp, vLLM, Ollama, LM Studio, ...). No cloud LLM is required, and your FASTA files stay on your machine.

## How it works

```
User request
     |
     v
 Agent (agent.py) <---------> LLM server (OpenAI-compatible API, tool calling)
     |
     +--> list_fasta_files(directory)
     +--> run_ecoml_vp(fasta_path) --> EcoML-VP (BLAST + Abricate + ML model)
```

1. The agent sends your request and the tool definitions to the LLM.
2. When the LLM asks for a tool, the agent validates the arguments, runs the tool, and returns a structured result (`{"ok": true, "data": ...}` or `{"ok": false, "error": ...}`).
3. This repeats until the LLM gives a final answer or the iteration limit is reached.

Reliability and safety features:

- Tools can only access files under the input directory (`/input` in Docker). Path traversal (`../`) and symlink escapes are blocked.
- The pipeline is launched with an argument list (no shell), a timeout, and size-limited output.
- Iteration limit, duplicate-call guard, and LLM request timeout/retries prevent runaway loops.
- Tool errors are passed back to the LLM instead of crashing the agent. The system prompt tells the model to answer only from tool output.
- Optional JSONL logs record each request, tool call, status, and latency.

## Requirements

- Docker
- An OpenAI-compatible LLM server running a model that supports tool calling
- *E. coli* genome FASTA files (`.fasta`, `.fa`, `.fna`). An example genome (NCBI RefSeq assembly `GCF_000022225.1`) is included in `input/`.

The EcoML-VP pipeline and its prediction model are included in this repository. The Docker image installs BLAST and Abricate and fetches the pinned `abricate_reproducible` files during the image build; users do not need to install Abricate on the host. The LLM model and inference server are not included. Smaller LLMs may be less reliable at choosing tools and arguments.

## Quick start

### 1. Clone

EcoML-VP is included in this repository, so a regular clone is sufficient:

```bash
git clone https://github.com/erdbwjd00/EcoML-VP-AI-Agent.git
cd EcoML-VP-AI-Agent
```

### 2. Start an LLM server

Use any OpenAI-compatible server with tool calling enabled. Typical defaults:

| Server | Typical base URL | Tool-calling note |
|---|---|---|
| llama.cpp (`llama-server`) | `http://127.0.0.1:8080/v1` | start it with `--jinja` |
| vLLM | `http://127.0.0.1:8000/v1` | enable auto tool choice and a tool-call parser (see vLLM docs) |
| Ollama | `http://127.0.0.1:11434/v1` | choose a model that supports tools |
| LM Studio | `http://127.0.0.1:1234/v1` | choose a tool-capable model |

Check that the server is up and note the model id:

```bash
curl http://127.0.0.1:8080/v1/models
```

### 3. Build the image

```bash
docker build -t ecoml-vp-ai-agent:latest .
```

The Docker build needs internet access to fetch the pinned `abricate_reproducible` source and database files from GitHub. No host-side Abricate installation is required.

### 4. Run the agent

**Linux** (container shares the host network):

```bash
docker run --rm -it \
  --network host \
  -e LLM_BASE_URL=http://127.0.0.1:8080/v1 \
  -e LLM_MODEL=<model-id> \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/logs:/app/logs" \
  ecoml-vp-ai-agent:latest
```

**macOS / Windows (Docker Desktop):**

```bash
docker run --rm -it \
  -e LLM_BASE_URL=http://host.docker.internal:8080/v1 \
  -e LLM_MODEL=<model-id> \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/logs:/app/logs" \
  ecoml-vp-ai-agent:latest
```

On Docker Desktop the LLM server must accept connections from the container (for llama.cpp, add `--host 0.0.0.0`).

Notes:

- `input/` in the repository is mounted as `/input` and contains the example genome. To analyze your own data, put the files in `input/` (git ignores everything there except the examples) or mount another directory instead. The agent can only see files under `/input`.
- Replace `<model-id>` with an id from the server's `/v1/models` response. Some servers (for example llama.cpp serving a single model) accept any name.
- Each run handles one request and then exits.

### 5. Ask for an analysis

At the `User:` prompt, use container paths:

```
List the FASTA files in /input
Analyze /input/GCF_000022225.1.fna
Analyze every FASTA file in /input and summarize each result separately
```

The agent replies in the language you write in, if the model supports it.

When it finishes, it prints a status line:

```
[status=ok iterations=3 tool_calls=2 latency=41230.5ms]
```

`status` is one of `ok`, `max_iterations`, `llm_error`, `empty_response`, or `truncated`.

## Configuration

All settings are environment variables (`-e NAME=value` with `docker run`).

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `default` | Model id sent in each request |
| `LLM_API_KEY` | `local` | API key, for servers that require one |
| `INPUT_DIR` | `input/` next to `agent.py` (`/input` in Docker) | The only directory the tools may access; relative paths are resolved against it |
| `AGENT_MAX_ITERATIONS` | `10` | Maximum LLM/tool rounds per request |
| `LLM_TIMEOUT_SEC` | `120` | Timeout per LLM request |
| `LLM_MAX_RETRIES` | `2` | Automatic retries for LLM requests |
| `LLM_MAX_TOKENS` | `2048` | Max tokens per LLM response (reasoning models need room to think) |
| `TOOL_TIMEOUT_SEC` | `600` | Timeout for one EcoML-VP run |
| `AGENT_LOG_PATH` | `/app/logs/agent.jsonl` (Docker) | JSONL log file |

## Logs

Each request appends JSON lines to the log file: `request_start`, `tool_call` (tool name, arguments, success, latency), and `request_end` (status, iterations, total latency). Mount a host directory at `/app/logs` (as in the run commands above) to keep logs after the container exits. Logs can contain your prompts and file paths, so do not commit or share them.

## Run the tests

The tests use a scripted mock LLM, so no model server or Docker is needed.

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Run it from the repository root. Use `python -m pytest` rather than `pytest` so the root directory is on the import path.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `LLM request failed: APIConnectionError` | The server is not reachable. Verify with `curl <LLM_BASE_URL>/models`. On Linux use `--network host`; on Docker Desktop use `host.docker.internal`. |
| `LLM request failed: NotFoundError` | `LLM_MODEL` does not match a model id from `/v1/models`. |
| The model answers without running any tool | Tool calling is not enabled on the server, or the model does not support it (for llama.cpp, start with `--jinja`). |
| `access denied: path must be inside ...` | Use a path under the mounted `/input` directory, not a host path. |
| `FASTA file not found` | Check the `-v` mount and the file name (`.fasta`, `.fa`, or `.fna`). |
| `abricate_reproducible/bin/abricate` not found | Rebuild the image and check that the Docker build can reach GitHub to fetch the pinned Abricate files. |
| Very slow responses | Common on CPU or with reasoning models. Try a smaller or non-reasoning model, or a GPU. Raise `LLM_TIMEOUT_SEC` if requests time out. |
| `status=max_iterations` | The model kept calling tools without finishing. Try a stronger model or raise `AGENT_MAX_ITERATIONS`. |
| `status=truncated` | The response hit the token limit. Raise `LLM_MAX_TOKENS`. |

## Optional: verify the Docker environment

Run EcoML-VP directly, without the LLM:

```bash
docker run --rm \
  -w /app/EcoML-VP \
  -v "$(pwd)/input:/input" \
  ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  python main.py /input/GCF_000022225.1.fna
```

Check the bundled tools:

```bash
docker run --rm ecoml-vp-ai-agent:latest conda run --no-capture-output -n ecoml blastn -version
docker run --rm ecoml-vp-ai-agent:latest conda run --no-capture-output -n ecoml abricate --list
docker run --rm -w /app/EcoML-VP ecoml-vp-ai-agent:latest ./abricate_reproducible/bin/abricate --list
```

## Data and privacy

- FASTA files are mounted at runtime and are never copied into the image.
- `input/` ships only public NCBI RefSeq example genomes (`GCF_*.fna`). `.gitignore` excludes every other file in that folder, so your own data is not committed by accident.
- The included `EcoML-VP/` directory contains the pipeline, its prediction model, and reference data tables. Do not add private or unauthorized datasets to the repository.
- No cloud service is required when you use a local model server.
- Do not commit logs or private datasets.

## Project structure

```
EcoML-VP-AI-Agent/
├── agent.py                # agent loop, tools, logging
├── tests/test_agent.py     # mock-LLM tests
├── input/                  # example FASTA files (other files here are git-ignored)
├── Dockerfile
├── requirements-agent.txt
├── requirements-dev.txt
├── pytest.ini
└── EcoML-VP/               # EcoML-VP pipeline and model files included in this repository
```

## License

See the license of the EcoML-VP project for the underlying analysis pipeline.