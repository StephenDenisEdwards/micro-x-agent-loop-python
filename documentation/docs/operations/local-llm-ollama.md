# Running Local LLMs with Ollama (Docker + GPU)

## Overview

This guide covers running LLMs locally using Ollama inside a Docker container with NVIDIA GPU acceleration, and integrating them with the agent loop via the Ollama provider.

## What is Ollama?

Ollama is an open-source tool that makes it easy to download and run LLMs locally on your machine.

### The problem it solves

Running an LLM locally normally requires you to:

- Find and download model weight files from various sources
- Install Python, PyTorch, CUDA libraries, and other dependencies
- Write or configure inference code
- Manage GPU memory, quantization settings, and model formats

### What Ollama does

It wraps all of that into a single application that:

1. **Downloads models** with one command (`ollama pull phi3:mini`) — like `docker pull` but for LLMs
2. **Serves them** via a REST API on port 11434 — any app can send HTTP requests to get responses
3. **Manages GPU/CPU memory** — automatically loads models into VRAM, unloads when idle
4. **Handles quantization** — models come pre-optimized (e.g., Q4 = 4-bit) so they fit on consumer GPUs

Think of it as:

- **Docker** is to applications what **Ollama** is to LLMs
- It's like a local, self-hosted version of the OpenAI API — same concept (send prompt, get response), but everything runs on your hardware

### Why run it inside Docker?

You don't have to — Ollama has a native Windows installer. But Docker keeps it isolated from your system, makes it easy to start/stop/remove, and ensures the CUDA dependencies don't conflict with anything else.

## Prerequisites

| Prerequisite | How to install |
|---|---|
| Docker Desktop | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — enable WSL2 backend |
| NVIDIA GPU driver | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) |
| NVIDIA Container Toolkit | [install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) |

Verify with:

```bash
docker --version
nvidia-smi
```

Confirm the NVIDIA runtime is registered in Docker:

```bash
docker info | grep -i nvidia
# Should show: Runtimes: ... nvidia ...
```

## Recommended models (4GB VRAM)

With 4GB VRAM (e.g., RTX 3050), all 4 models can be downloaded but only one runs at a time. Ollama automatically loads and unloads models as needed.

| Model | Size | Good for |
|---|---|---|
| `phi3:mini` | ~2.3GB | General purpose, strong for size |
| `llama3.2:3b` | ~2GB | Meta's latest small model |
| `mistral:7b` | ~4GB | Tight fit on 4GB, good quality (Q4 quantized by default) |
| `gemma2:2b` | ~1.6GB | Google's small model |

Total disk space needed: ~10GB for all 4 models.

## Setup instructions

### Step 1: Start the Ollama container

```bash
docker run -d --gpus all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

What each flag does:

| Flag | Purpose |
|---|---|
| `docker run` | Creates and starts a new container |
| `-d` | **Detached** — runs in the background like a service |
| `--gpus all` | Passes your NVIDIA GPU into the container for CUDA-accelerated inference |
| `-v ollama:/root/.ollama` | **Volume mount** — persistent storage for downloaded models; survives container restarts |
| `-p 11434:11434` | **Port mapping** — exposes Ollama's API on `localhost:11434` |
| `--name ollama` | Names the container "ollama" for easy reference |
| `ollama/ollama` | The official Ollama Docker image from Docker Hub |

### Step 2: Pull all models

```bash
docker exec ollama ollama pull phi3:mini
docker exec ollama ollama pull llama3.2:3b
docker exec ollama ollama pull mistral:7b
docker exec ollama ollama pull gemma2:2b
```

### Step 3: Verify models are available

```bash
docker exec ollama ollama list
```

## Usage with Ollama directly

### Interactive chat

```bash
docker exec -it ollama ollama run phi3:mini
docker exec -it ollama ollama run llama3.2:3b
docker exec -it ollama ollama run mistral:7b
docker exec -it ollama ollama run gemma2:2b
```

### REST API

```bash
# Change the "model" value to switch between models
curl http://localhost:11434/api/generate -d '{"model":"phi3:mini","prompt":"Hello!"}'
curl http://localhost:11434/api/generate -d '{"model":"llama3.2:3b","prompt":"Hello!"}'
curl http://localhost:11434/api/generate -d '{"model":"mistral:7b","prompt":"Hello!"}'
curl http://localhost:11434/api/generate -d '{"model":"gemma2:2b","prompt":"Hello!"}'
```

## Agent loop integration

### Ollama provider

The agent loop includes an `ollama` provider (`providers/ollama_provider.py`) that subclasses the OpenAI provider and points at the local Ollama API (`http://localhost:11434/v1`). Ollama exposes an OpenAI-compatible API, so no additional dependencies are required.

The provider automatically supplies a dummy API key (the OpenAI SDK requires a non-empty string, but Ollama doesn't validate it).

### Configuration profiles

There are two variants of config for each model:

- **Local only** — fully offline, all secondary features disabled. No cloud API key needed.
- **Hybrid** — main conversation runs locally on Ollama (free), secondary features (compaction, sub-agents, classification, tool summarization) use Anthropic Haiku via the cloud. Requires `ANTHROPIC_API_KEY` in `.env`.

#### Local-only configs

| Config file | Model |
|---|---|
| `config-standard-ollama-phi3.json` | `phi3:mini` |
| `config-standard-ollama-llama3.json` | `llama3.2:3b` |
| `config-standard-ollama-mistral.json` | `mistral:7b` |
| `config-standard-ollama-gemma2.json` | `gemma2:2b` |

These configs disable features that require additional LLM calls:

| Disabled feature | Why |
|---|---|
| `PromptCachingEnabled` | Anthropic-specific API feature; not supported by Ollama |
| `CompactionStrategy` | Requires a secondary LLM call to summarize conversation history |
| `SubAgentsEnabled` | Spawns sub-agent LLM calls needing a secondary model |
| `ModeAnalysisEnabled` | Feeds into Stage 2 LLM classification |
| `Stage2ClassificationEnabled` | Uses a separate provider/model for prompt classification |
| `ToolSearchEnabled` | Requires an LLM call to rank and discover tools |
| `ToolResultSummarizationEnabled` | Uses a secondary model to summarize large tool results |

With 4GB VRAM, only one model can be loaded at a time, and these features default to cloud models (Anthropic Haiku) in `config-base.json`. Without a cloud API key, they would fail.

#### Hybrid configs

| Config file | Model |
|---|---|
| `config-standard-ollama-phi3-hybrid.json` | `phi3:mini` |
| `config-standard-ollama-llama3-hybrid.json` | `llama3.2:3b` |
| `config-standard-ollama-mistral-hybrid.json` | `mistral:7b` |
| `config-standard-ollama-gemma2-hybrid.json` | `gemma2:2b` |

These configs route secondary features to Anthropic Haiku in the cloud:

| Feature | Provider | Model |
|---|---|---|
| Main conversation | `ollama` (local) | Selected Ollama model |
| Compaction | `anthropic` (cloud) | `claude-haiku-4-5-20251001` |
| Sub-agents | `anthropic` (cloud) | `claude-haiku-4-5-20251001` |
| Stage 2 classification | `anthropic` (cloud) | `claude-haiku-4-5-20251001` |
| Tool result summarization | `anthropic` (cloud) | `claude-haiku-4-5-20251001` |
| Tool search | `ollama` (local) | Same Ollama model |

**Tradeoffs:**

- **Cost**: Main conversation is free (local). Secondary calls use Haiku ($1/MTok input, $5/MTok output) — very cheap since they're short summarization/classification calls.
- **Latency**: Secondary calls go over the network but are small. Main conversation latency depends on local GPU speed.
- **Dependency**: Requires `ANTHROPIC_API_KEY` in `.env` for the secondary features to work.

#### Default config

`config-standard-ollama.json` is a pointer (via `ConfigFile` indirection) to `config-standard-ollama-phi3.json`.

### Running the agent

```bash
# Local only — fully offline
python -m micro_x_agent_loop --config config-standard-ollama-phi3.json
python -m micro_x_agent_loop --config config-standard-ollama-llama3.json
python -m micro_x_agent_loop --config config-standard-ollama-mistral.json
python -m micro_x_agent_loop --config config-standard-ollama-gemma2.json

# Hybrid — local main conversation, cloud secondary features
python -m micro_x_agent_loop --config config-standard-ollama-phi3-hybrid.json
python -m micro_x_agent_loop --config config-standard-ollama-llama3-hybrid.json
python -m micro_x_agent_loop --config config-standard-ollama-mistral-hybrid.json
python -m micro_x_agent_loop --config config-standard-ollama-gemma2-hybrid.json
```

### Pricing

All Ollama models are configured with $0 pricing in `config-base.json` since inference is local:

```json
"ollama/phi3:mini": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/llama3.2:3b": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/mistral:7b": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"ollama/gemma2:2b": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 }
```

## Container management

```bash
# Stop the container
docker stop ollama

# Start it again (models persist in the volume)
docker start ollama

# View logs
docker logs ollama

# Remove the container (models still saved in the volume)
docker rm ollama

# Remove the volume (deletes all downloaded models)
docker volume rm ollama
```
