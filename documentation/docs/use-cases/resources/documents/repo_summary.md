# GitHub Repository Summary
_Generated: 2026-03-03 07:35_

**Total repositories:** 39

---

## [micro-x-agent-loop-python](https://github.com/StephenDenisEdwards/micro-x-agent-loop-python)

**Language:** Python  **Visibility:** public  **Updated:** 2026-03-03

_A general personal assistant AI agent loop built with Python and using the Anthropic Claude or OpenAI and LLMs_

**README Summary:**

A minimal AI agent loop built with Python and the Anthropic Claude API. The agent runs in a REPL, takes natural-language prompts, and autonomously calls tools to get things done. Responses stream in real time as Claude generates them.

This is the Python port of [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet). Both projects share the same architecture, tools, and configuration format.


- **Streaming responses** — text appears word-by-word as Claude generates it
- **Parallel tool execution** — multiple tool calls in a single turn run concurrently via `asyncio.gather`
- **Automatic retry** — tenacity-based exponential backoff on API rate limits
- **Conversation compaction** — LLM-based summarization keeps long conversations within context limits
- **MCP tool servers** — extend the agent with external tools via the Model Context Protocol (stdio and HTTP transports)

_...README truncated for brevity._

---

## [micro-x-steves-obsidian](https://github.com/StephenDenisEdwards/micro-x-steves-obsidian)

**Language:** Python  **Visibility:** public  **Updated:** 2026-02-25

**README Summary:**

A proof-of-concept for Retrieval-Augmented Generation (RAG) over an [Obsidian](https://obsidian.md) knowledge vault. The vault contains interconnected notes about **agent loop compaction** — the techniques used to manage context window consumption in LLM-powered agent systems. A Python pipeline ingests the vault into a vector database and answers natural-language questions grounded in the vault's content.


[Obsidian](https://obsidian.md) is a markdown-based knowledge management tool built around three principles:

- **Local-first markdown files.** Every note is a plain `.md` file on disk. No proprietary format, no database — just files you own. This makes Obsidian vaults trivially accessible to external tools like this RAG pipeline.

- **Bidirectional wiki links.** Notes reference each other with `[[wiki links]]` (e.g., `[[Sliding Window]]`). These links create a knowledge graph — a web of connections between concepts. Obsidian visualizes this graph and lets you navigate it, but the links are just plain text in the markdown files.

_...README truncated for brevity._

---

## [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet)

**Language:** C#  **Visibility:** public  **Updated:** 2026-02-24

**README Summary:**

A minimal AI agent loop built with .NET 8 and the Anthropic Claude API. The agent runs in a REPL, takes natural-language prompts, and autonomously calls tools to get things done. Responses stream in real time as Claude generates them.


- **Streaming responses** — text appears word-by-word as Claude generates it
- **Parallel tool execution** — multiple tool calls in a single turn run concurrently
- **Automatic retry** — Polly-based exponential backoff on API rate limits
- **Configurable limits** — max tool result size and conversation history length with clear warnings
- **Token compaction** — LLM-based conversation summarization to preserve context intelligently
- **Conditional tools** — Gmail, Calendar, web search, and usage tools only load when credentials are present
- **MCP integration** — dynamic tool discovery from external servers via Model Context Protocol

_...README truncated for brevity._

---

## [interview-assist-2](https://github.com/StephenDenisEdwards/interview-assist-2)

**Language:** C#  **Visibility:** public  **Updated:** 2026-02-19

**README Summary:**

Real-time interview assistance application that captures audio, transcribes speech via Deepgram, and detects questions using LLM-based intent classification.


- .NET 8.0 SDK or later
- Windows 10/11 (required for audio capture)
- Deepgram API key (transcription)
- OpenAI API key (intent detection, optional)


dotnet build interview-assist-2.sln

set DEEPGRAM_API_KEY=your-deepgram-key
set OPENAI_API_KEY=your-openai-key

dotnet run --project Interview-assist-transcription-detection-console

_...README truncated for brevity._

---

## [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers)

**Language:** C#  **Visibility:** public  **Updated:** 2026-02-19

**README Summary:**

A collection of [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) servers built with .NET 10 and the [ModelContextProtocol](https://www.nuget.org/packages/ModelContextProtocol) SDK.




- .NET 10 SDK

---

## [micro-x-agent-loop](https://github.com/StephenDenisEdwards/micro-x-agent-loop)

**Language:** TypeScript  **Visibility:** public  **Updated:** 2026-02-15

**README Summary:**

A lightweight autonomous AI agent loop, starting simple and evolving toward a full-featured personal AI assistant inspired by [OpenClaw](https://github.com/openclaw/openclaw).


This project begins as a minimal agent loop — the core cycle of perceiving, reasoning, and acting that underpins autonomous AI agents. The goal is to build a solid foundation first, then incrementally add capabilities to approach the functionality of projects like OpenClaw: an open-source autonomous agent that executes real-world tasks via LLMs across multiple platforms and integrations.


- Basic prompt-response loop with an LLM
- Tool/action execution framework
- Simple memory and context management

- Plugin/skill system for extensible capabilities
- File system, web browsing, and command execution skills
- Multi-model support

_...README truncated for brevity._

---

## [torch-playground](https://github.com/StephenDenisEdwards/torch-playground)

**Language:** Python  **Visibility:** public  **Updated:** 2026-02-03

_No README available._

---

## [interview-assist](https://github.com/StephenDenisEdwards/interview-assist)

**Language:** C#  **Visibility:** private  **Updated:** 2026-01-19

_No README available._

---

## [micro-x-ai-assist](https://github.com/StephenDenisEdwards/micro-x-ai-assist)

**Language:** C#  **Visibility:** public  **Updated:** 2025-12-02

**README Summary:**

A .NET8 console/hosted app that captures Windows system audio from a selected output device (WASAPI loopback), resamples it to16 kHz PCM mono, and streams it to Azure Cognitive Services Speech for live transcription.

Use it to transcribe remote participants in Microsoft Teams (or any app routed to the chosen output device). Partial and final results are logged to the console via Serilog.


- Device selection
- `AudioDeviceSelector` chooses an active Windows render endpoint. If `Audio:DeviceNameContains` is set, the first device whose friendly name contains that substring is selected; otherwise the default multimedia endpoint is used.
- Loopback capture
- `LoopbackSource` uses NAudio `WasapiLoopbackCapture` to capture the audio leaving the selected output device into a buffer.
- Resampling and format conversion

_...README truncated for brevity._

---

## [GeminiLiveConsole](https://github.com/StephenDenisEdwards/GeminiLiveConsole)

**Language:** C#  **Visibility:** public  **Updated:** 2025-11-21

_Basic console app for Gemini Interview Assist_

**README Summary:**

C# console prototype mirroring the TypeScript `LiveManager`.


- Captures microphone audio (16 kHz, mono, 16-bit PCM) with NAudio.
- Streams audio frames over WebSocket to Gemini Live (placeholder protocol).
- Parses transcripts and tool/function calls (`report_intent`).
- Computes RMS for optional volume visualization.


Set your API key:

setx API_KEY your_key_here

Restart the terminal after setting.


cd dotnet/GeminiLiveConsole

_...README truncated for brevity._

---

## [my_google_ai_studio_app](https://github.com/StephenDenisEdwards/my_google_ai_studio_app)

**Language:** TypeScript  **Visibility:** public  **Updated:** 2025-11-20

_My first app_

**README Summary:**

<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>


This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/drive/1PCOWEHcb4d775t1jVbM-Yp_PjhpBWy8H


**Prerequisites:**  Node.js

1. Install dependencies:
`npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key

_...README truncated for brevity._

---

## [MyAiBuiltProject](https://github.com/StephenDenisEdwards/MyAiBuiltProject)

**Language:** C#  **Visibility:** public  **Updated:** 2025-11-07

**README Summary:**

﻿# Model Context Protocol

[Model Context Protocol - Documentation](https://modelcontextprotocol.io/docs/getting-started/intro)

[MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)

[C# SDK with Samples](https://github.com/modelcontextprotocol/csharp-sdk/tree/main)

[MCP Technical Documentation](https://github.com/modelcontextprotocol/modelcontextprotocol)

---

## [micro-x-ai-projects-documents](https://github.com/StephenDenisEdwards/micro-x-ai-projects-documents)

**Visibility:** public  **Updated:** 2025-11-06

**README Summary:**

Contains documents related to AI projects

---

## [MauiBlazorAutoB2cApp-AzureAI](https://github.com/StephenDenisEdwards/MauiBlazorAutoB2cApp-AzureAI)

**Language:** C#  **Visibility:** public  **Updated:** 2025-11-02

_No README available._

---

## [my-modelcontextprotocol](https://github.com/StephenDenisEdwards/my-modelcontextprotocol)

**Visibility:** public  **Updated:** 2025-10-30

_No README available._

---

## [MauiApp-Aspire](https://github.com/StephenDenisEdwards/MauiApp-Aspire)

**Language:** C#  **Visibility:** public  **Updated:** 2025-10-06

**README Summary:**

_README contains only non-text content._

---

## [MauiBlazorAutoB2bApp](https://github.com/StephenDenisEdwards/MauiBlazorAutoB2bApp)

**Language:** C#  **Visibility:** public  **Updated:** 2025-09-29

_No README available._

---

## [KafkaPoC](https://github.com/StephenDenisEdwards/KafkaPoC)

**Language:** C#  **Visibility:** public  **Updated:** 2025-08-12

**README Summary:**

﻿# How can I get started with PoC type projects to demonstrate Kafka capabilities. I typically use .NET Core as my development platform.

Here's a structured, step-by-step approach to quickly and effectively create **Proof of Concept (PoC)** projects demonstrating Kafka capabilities using  **.NET Core** .




The simplest and quickest way to get Kafka running locally:

* Use a Docker Compose file from the official Confluent Kafka quickstart:

curl --silent --output docker-compose.yml \
https://raw.githubusercontent.com/confluentinc/cp-all-in-one/7.6.0-post/cp-all-in-one/docker-compose.yml

docker-compose up -d

_...README truncated for brevity._

---

## [ConsoleAppFeseniusInterSystemDotCore](https://github.com/StephenDenisEdwards/ConsoleAppFeseniusInterSystemDotCore)

**Language:** C#  **Visibility:** private  **Updated:** 2025-07-24

_No README available._

---

## [MyBlazorWasmAadApp](https://github.com/StephenDenisEdwards/MyBlazorWasmAadApp)

**Language:** HTML  **Visibility:** private  **Updated:** 2025-06-10

_No README available._

---

## [tingler-sign-in-maui](https://github.com/StephenDenisEdwards/tingler-sign-in-maui)

**Language:** C#  **Visibility:** public  **Updated:** 2025-05-31

_No README available._

---

## [AADConsoleAndWebTest](https://github.com/StephenDenisEdwards/AADConsoleAndWebTest)

**Language:** PowerShell  **Visibility:** private  **Updated:** 2025-05-26

_No README available._

---

## [MsIdWebApp](https://github.com/StephenDenisEdwards/MsIdWebApp)

**Language:** PowerShell  **Visibility:** private  **Updated:** 2025-05-25

**README Summary:**

page_type: sample
name: An ASP.NET Core web app authenticating users against Azure AD for Customers using Microsoft Identity Web
description:
languages:
- csharp
products:
- entra-external-id
- microsoft-identity-web
urlFragment: ms-identity-ciam-dotnet-tutorial-1-sign-in-aspnet-core-mvc
extensions:
services:
- ms-identity
platform:
- DotNet
endpoint:

_...README truncated for brevity._

---

## [MauiBlazorServerB2bApp](https://github.com/StephenDenisEdwards/MauiBlazorServerB2bApp)

**Language:** HTML  **Visibility:** public  **Updated:** 2025-05-19

_No README available._

---

## [MauiBlazorWasmB2bApp](https://github.com/StephenDenisEdwards/MauiBlazorWasmB2bApp)

**Language:** HTML  **Visibility:** public  **Updated:** 2025-05-19

_No README available._

---

## [AngularApp1](https://github.com/StephenDenisEdwards/AngularApp1)

**Language:** TypeScript  **Visibility:** private  **Updated:** 2025-04-25

_No README available._

---

## [OpenAi](https://github.com/StephenDenisEdwards/OpenAi)

**Language:** Python  **Visibility:** public  **Updated:** 2025-04-18

**README Summary:**

Just messing about with AI models and Python libraries

---

## [HorizonLogAnalyser](https://github.com/StephenDenisEdwards/HorizonLogAnalyser)

**Language:** C#  **Visibility:** public  **Updated:** 2025-04-18

_No README available._

---

## [Snake_2](https://github.com/StephenDenisEdwards/Snake_2)

**Language:** Python  **Visibility:** private  **Updated:** 2025-03-02

**README Summary:**

After cloning the repository, run:

pip install -r requirements.txt

---

## [Snake](https://github.com/StephenDenisEdwards/Snake)

**Language:** Python  **Visibility:** private  **Updated:** 2025-02-25

**README Summary:**

After cloning the repository, run:

pip install -r requirements.txt

---

## [VCode](https://github.com/StephenDenisEdwards/VCode)

**Language:** Python  **Visibility:** private  **Updated:** 2025-02-07

_No README available._

---

## [MauiApp](https://github.com/StephenDenisEdwards/MauiApp)

**Language:** C#  **Visibility:** private  **Updated:** 2025-01-23

_No README available._

---

## [ConsoleCopilotCompleteApp](https://github.com/StephenDenisEdwards/ConsoleCopilotCompleteApp)

**Language:** C#  **Visibility:** private  **Updated:** 2025-01-23

_No README available._

---

## [ConsoleCopilotApp](https://github.com/StephenDenisEdwards/ConsoleCopilotApp)

**Language:** C#  **Visibility:** private  **Updated:** 2025-01-19

_No README available._

---

## [MyFirstMauiApp](https://github.com/StephenDenisEdwards/MyFirstMauiApp)

**Language:** C#  **Visibility:** private  **Updated:** 2025-01-18

_No README available._

---

## [MyPython](https://github.com/StephenDenisEdwards/MyPython)

**Language:** Python  **Visibility:** public  **Updated:** 2020-12-03

**README Summary:**

_README contains only non-text content._

---

## [RedgateCodeTest](https://github.com/StephenDenisEdwards/RedgateCodeTest)

**Language:** C#  **Visibility:** public  **Updated:** 2020-11-30

**README Summary:**

_README contains only non-text content._

---

## [Elekta](https://github.com/StephenDenisEdwards/Elekta)

**Language:** C#  **Visibility:** public  **Updated:** 2020-11-23

**README Summary:**

I have refactored the project and provided 3 possible solutions. My prefered solution is to use the visitor pattern as it doesn't require the use of reflection.

I have retained the original project (PetReporting) and annotated it with TODO comments indicating the issues I would highlight to the programmer about the code.

**Elekta\PetReporting.Dynamic** dotnet run

Or run the **PetReporting.Dynamic.ConsoleApp** project in the VS solution.


**Owners name,Date Joined Practice,Number Of Visits,Number of Lives**

Jim Rogers, 23/11/2020 21:46:35, 5,

Tony Smith, 13/07/1985 00:00:00, 10,

Steve Roberts, 06/05/2002 00:00:00, 20, 9

_...README truncated for brevity._

---

## [TensorflowEdu](https://github.com/StephenDenisEdwards/TensorflowEdu)

**Visibility:** public  **Updated:** 2020-09-10

_Tensorflow learning_

_No README available._

---
