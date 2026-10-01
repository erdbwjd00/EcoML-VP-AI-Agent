# EcoML-VP Local AI Agent

A local AI agent for analyzing *E. coli* FASTA files with the [EcoML-VP](https://github.com/erdbwjd00/EcoML-VP) pipeline.

The agent uses a locally hosted Qwen3 model through an OpenAI-compatible API and can invoke the EcoML-VP analysis pipeline as a tool.

## Architecture

```text
User
  |
  v
EcoML-VP AI Agent
  |
  +----> Local Qwen3 Server
  |       OpenAI-compatible API
  |       http://127.0.0.1:8080/v1
  |
  +----> EcoML-VP
          |
          +----> BLAST
          +----> Abricate
          +----> ML model

The Qwen3 model and the EcoML-VP analysis environment are separate components.

The Docker image contains the EcoML-VP analysis environment, while the local Qwen3 model is provided by a separate inference server.

Requirements
Docker

A locally running Qwen3-compatible inference server

An OpenAI-compatible API endpoint for the local model

An E. coli FASTA file for analysis

The agent has been tested with a Qwen3 model served through an OpenAI-compatible API.

Project Structure
EcoML-VP-AI-Agent/
├── agent.py
├── Dockerfile
├── requirements-agent.txt
├── .gitignore
├── .gitmodules
└── EcoML-VP/

EcoML-VP/ is included as a Git submodule.

Clone the Repository
Clone the repository together with its submodule:

git clone --recurse-submodules https://github.com/erdbwjd00/EcoML-VP-AI-Agent.git
cd EcoML-VP-AI-Agent

If the repository was already cloned without submodules:

git submodule update --init --recursive

1. Start the Local Qwen3 Server
The AI agent requires a locally running Qwen3-compatible server.

The server must expose an OpenAI-compatible endpoint such as:

http://127.0.0.1:8080/v1

Verify that the model server is running:

curl http://127.0.0.1:8080/v1/models

A successful response should contain at least one available model.

The exact command used to start the Qwen3 server depends on the inference backend and local hardware. The agent does not download or manage the LLM model itself.

2. Build the Docker Image
Build the EcoML-VP AI Agent image:

docker build -t ecoml-vp-ai-agent:latest .

You can validate the Dockerfile before building:

docker build --check .

The image installs:

Python 3.9

BLAST

Abricate

Abricate databases

EcoML-VP Python dependencies

AI Agent dependencies

3. Verify the Docker Environment
Check Python:

docker run --rm ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  python --version

Check scikit-learn:

docker run --rm ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  python -c "import pandas, sklearn; print('pandas OK'); print('sklearn', sklearn.__version__)"

Check BLAST:

docker run --rm ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  blastn -version

Check Abricate:

docker run --rm ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  abricate --version

Check Abricate databases:

docker run --rm ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  abricate --list

4. Test EcoML-VP Directly
FASTA files can be mounted into the container.

For example, if a FASTA file is located at:

/path/to/your/file.fasta

mount its containing directory:

docker run --rm \
  -w /app/EcoML-VP \
  -v "/path/to/your:/input" \
  ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  python main.py /input/file.fasta

The container should return an EcoML-VP result such as:

Pathotype-negative

The FASTA file remains on the host machine and is mounted into the container at runtime.

5. Run the AI Agent
To run the interactive local AI agent:

docker run --rm -it \
  --network host \
  -e QWEN_BASE_URL=http://127.0.0.1:8080/v1 \
  ecoml-vp-ai-agent:latest

The agent will display:

========================================
       EcoML-VP Local AI Agent
========================================

User:

Enter a natural-language request.

For example:

/input/sample.fasta 파일을 분석해줘

6. Analyze a FASTA File Through the Agent
Mount the directory containing the FASTA file:

docker run --rm -it \
  --network host \
  -e QWEN_BASE_URL=http://127.0.0.1:8080/v1 \
  -v "/path/to/fasta/files:/input" \
  ecoml-vp-ai-agent:latest

Then enter:

/input/sample.fasta 파일을 분석해줘

The agent sends the request to the local Qwen3 model.

Qwen3 determines whether the EcoML-VP analysis tool should be called and, when appropriate, invokes the EcoML-VP pipeline with the specified FASTA path.

The resulting analysis is then returned to the user.

7. Docker Networking
There are two common ways to connect the agent container to the local model server.

Host Networking
If the Qwen3 server is running directly on the host machine:

docker run --rm -it \
  --network host \
  -e QWEN_BASE_URL=http://127.0.0.1:8080/v1 \
  ecoml-vp-ai-agent:latest

With --network host, the container can access services exposed on the host using 127.0.0.1.

Docker Network
Alternatively, the Qwen3 server can run in another Docker container on a shared Docker network.

Create a network:

docker network create ecoml-network

The Qwen3 container should be connected to this network with the container name:

qwen-server

The agent can then use:

http://qwen-server:8080/v1

as its API endpoint.

The Dockerfile uses this container-to-container address as its default:

QWEN_BASE_URL=http://qwen-server:8080/v1

When using host networking, override it with:

-e QWEN_BASE_URL=http://127.0.0.1:8080/v1

8. FASTA Files and Volumes
FASTA files do not need to be copied into the Docker image.

Instead, mount a host directory:

-v "/path/to/fasta/files:/input"

Then use the container path:

/input/sample.fasta

This keeps user data outside the Docker image.

Do not add private datasets, server-specific directories, or large FASTA files to the Git repository.

9. Troubleshooting
Qwen3 Connection Error
Check that the local model server is running:

curl http://127.0.0.1:8080/v1/models

If this works on the host but the agent cannot connect, make sure the agent was started with:

--network host

and:

-e QWEN_BASE_URL=http://127.0.0.1:8080/v1

qwen-server Cannot Be Resolved
If you see:

Could not resolve host: qwen-server

the container is not connected to a Docker network containing a container named qwen-server.

Use host networking instead:

--network host

and:

QWEN_BASE_URL=http://127.0.0.1:8080/v1

FASTA File Not Found
Make sure the host directory is mounted:

-v "/path/to/fasta/files:/input"

and use the container path:

/input/filename.fasta

BLAST Database Error
The EcoML-VP E. coli BLAST database is included in the EcoML-VP source tree.

You can verify it with:

docker run --rm \
  -w /app/EcoML-VP \
  ecoml-vp-ai-agent:latest \
  conda run --no-capture-output -n ecoml \
  blastdbcmd -db ecoli/e.coli_pathotype.fa -info

Privacy and Reproducibility
The repository does not require hard-coded host-specific paths or IP addresses.

Host-specific values such as:

/path/to/your
127.0.0.1

are supplied at runtime rather than stored in the repository.

FASTA files can also remain outside the Docker image and be mounted only when needed.

The local Qwen3 server is separate from the Docker image. No cloud LLM service is required by the agent when using a local OpenAI-compatible model endpoint.

Notes
The Docker image currently uses a Miniconda base image and creates a dedicated Python 3.9 environment for EcoML-VP.

The LLM inference server is intentionally not included in this image because model serving and EcoML-VP analysis are separate workloads.

License
See the license and documentation of the EcoML-VP project for information about the underlying analysis pipeline.