# Technology Stack Analysis - StephenDenisEdwards Repositories

## Repository Overview

| # | Repository | Primary Language | Last Updated | Status |
|---|------------|------------------|--------------|--------|
| 1 | micro-x-agent-loop-python | Python | 2026-02-19 | Active |
| 2 | micro-x-agent-loop-dotnet | C# | 2026-02-19 | Active |
| 3 | mcp-servers | C# | 2026-02-19 | Active |
| 4 | micro-x-agent-loop | TypeScript | 2026-02-15 | Active |
| 5 | interview-assist-2 | C# | 2026-02-14 | Active |
| 6 | torch-playground | Python | 2026-02-03 | Active |
| 7 | interview-assist | C# | 2026-01-19 | Private |
| 8 | micro-x-ai-assist | C# | 2025-12-02 | Active |
| 9 | GeminiLiveConsole | C# | 2025-11-21 | Active |
| 10 | my_google_ai_studio_app | TypeScript | 2025-11-20 | Active |

---

## 1. micro-x-agent-loop-python

**Description:** A minimal AI agent loop built with Python and the Anthropic Claude API

### Core Technologies
- **Language:** Python 3.11+
- **Package Manager:** uv (Rust-based, 10-100x faster than pip)
- **Runtime:** Python asyncio for concurrent operations

### Key Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| anthropic | ≥0.42.0 | Claude API (official SDK) |
| python-dotenv | ≥1.0.0 | Environment variable management |
| tenacity | ≥9.0.0 | Retry with exponential backoff |
| python-docx | ≥1.1.0 | Read .docx files |
| beautifulsoup4 | ≥4.12.0 | HTML parsing and conversion |
| lxml | ≥5.0.0 | XML/HTML processing |
| httpx | ≥0.27.0 | Async HTTP client |
| google-api-python-client | ≥2.150.0 | Gmail and Calendar API |
| google-auth-oauthlib | ≥1.2.0 | Google OAuth2 flow |
| loguru | ≥0.7.0 | Structured logging |
| mcp | ≥1.0.0 | Model Context Protocol client |

### Features
- Streaming responses from Claude API
- Parallel tool execution via asyncio.gather
- Automatic retry with exponential backoff
- LLM-based conversation compaction
- MCP tool server integration (stdio/HTTP)
- Gmail, Calendar, LinkedIn, Web tools
- WhatsApp integration via external Go bridge

---

## 2. micro-x-agent-loop-dotnet

**Description:** C#/.NET 8 implementation of the AI agent loop (original version)

### Core Technologies
- **Language:** C# 
- **Framework:** .NET 8 SDK
- **Build System:** dotnet CLI

### Key Dependencies
- **Anthropic.SDK** - Claude API
- **DotNetEnv** - Environment variable loading
- **Polly** - Retry with exponential backoff
- **DocumentFormat.OpenXml** - .docx file handling
- **HtmlAgilityPack** - HTML parsing
- **HttpClient** - HTTP requests
- **Google.Apis.Gmail.v1** - Gmail API
- **Google.Apis.Auth** - Google OAuth2
- **Serilog** - Structured logging
- **ModelContextProtocol** - MCP client

### Features
- Streaming responses
- Parallel tool execution
- Automatic retry (Polly)
- Token compaction
- MCP integration (stdio/HTTP)
- Cross-platform (Windows, macOS, Linux)

---

## 3. mcp-servers

**Description:** Collection of Model Context Protocol servers built with .NET 10

### Core Technologies
- **Language:** C#
- **Framework:** .NET 10 SDK
- **Protocol:** Model Context Protocol (MCP)

### Key Package
- **ModelContextProtocol** SDK from NuGet

### Servers
- **system-info** - OS, CPU, memory, disk, and network information

---

## 4. micro-x-agent-loop

**Description:** TypeScript implementation of the AI agent loop

### Core Technologies
- **Language:** TypeScript 5.9+
- **Runtime:** Node.js
- **Build System:** TypeScript compiler (tsc)
- **Module System:** ES Modules

### Key Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| @anthropic-ai/sdk | ^0.74.0 | Claude API |
| cheerio | ^1.2.0 | HTML parsing |
| dotenv | ^17.3.1 | Environment variables |
| googleapis | ^171.4.0 | Google APIs |
| linkedin-jobs-api | ^1.0.7 | LinkedIn job search |
| mammoth | ^1.11.0 | .docx conversion |

### Dev Dependencies
- **@types/node** ^25.2.3
- **typescript** ^5.9.3
- **vitest** ^4.0.18 (testing framework)

---

## 5. interview-assist-2

**Description:** Real-time interview assistance with audio capture and transcription

### Core Technologies
- **Language:** C#
- **Framework:** .NET 8.0 SDK
- **Platform:** Windows 10/11 (required for audio)
- **UI Framework:** Terminal.Gui

### Key Technologies
- **NAudio** - Windows audio capture
- **Deepgram API** - Speech transcription
- **OpenAI API** - Intent detection (optional)
- **xUnit** - Unit testing framework

### Project Structure
- **Interview-assist-library** - Core abstractions, intent detection
- **interview-assist-audio-windows** - Windows audio capture (NAudio)
- **Interview-assist-transcription-detection-console** - Terminal.Gui UI
- **Interview-assist-annotation-concept-e-console** - Ground truth annotation
- **Interview-assist-library-unit-tests** - xUnit tests
- **Interview-assist-library-integration-tests** - Integration tests

### Features
- Real-time audio capture (microphone)
- Live transcription via Deepgram
- LLM-based intent classification
- Recording/playback system
- Evaluation framework
- Interactive annotation tool

---

## 6. torch-playground

**Description:** Simple PyTorch experimentation

### Core Technologies
- **Language:** Python
- **Framework:** PyTorch

### Purpose
- Learning/testing PyTorch
- Matrix operations demo
- Mobile development test (edits on phone)

---

## 7. interview-assist (Private)

**Description:** Original interview assistance app with MAUI desktop UI

### Core Technologies
- **Language:** C#
- **Framework:** .NET 8 (library), .NET 10 (MAUI)
- **UI Framework:** .NET MAUI
- **Platform:** Windows desktop

### Key Technologies
- **NAudio** - Audio capture (WaveInEvent, WasapiLoopbackCapture)
- **OpenAI Realtime API** - Live transcription and AI responses
- **xUnit** - Testing

### Architecture
- **Observer pattern** - IRealtimeSink for event consumption
- **WebSocket** - Real-time API communication
- **Audio pipeline** - Resample to 16kHz mono PCM
- **Bounded channels** - Audio queue management (capacity 8)

### Project Structure
- **Interview-assist-library** - Core abstractions (net8.0)
- **interview-assist-audio-windows** - Audio capture (net8.0)
- **interview-assist-maui-desktop** - MAUI UI (net10.0-windows)
- **interview-assist-console-windows** - CLI application
- **Interview-assist-library-unit-tests** - xUnit tests
- **Interview-assist-library-integration-tests** - Integration tests

---

## 8. micro-x-ai-assist

**Description:** Teams remote STT - captures Windows system audio for transcription

### Core Technologies
- **Language:** C#
- **Framework:** .NET 8
- **Platform:** Windows 10/11

### Key Technologies
- **NAudio** - WASAPI loopback capture
- **Azure Cognitive Services Speech SDK** - Speech-to-text
- **Media Foundation** - Audio resampling
- **Serilog** - Logging

### Features
- WASAPI loopback capture (system audio)
- 16 kHz PCM mono resampling
- Live Azure Speech transcription
- Device selection by name substring
- Push stream architecture
- Partial and final transcription logging

### Services
- **AudioDeviceSelector** - Windows render endpoint selection
- **LoopbackSource** - WasapiLoopbackCapture wrapper
- **AudioResampler** - Media Foundation format conversion
- **CapturePump** - Chunking and push stream
- **SpeechPushClient** - Azure Speech SDK integration

---

## 9. GeminiLiveConsole

**Description:** Console app for Gemini Live API with audio streaming

### Core Technologies
- **Language:** C#
- **Framework:** .NET 8.0
- **Protocol:** WebSocket

### Key Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| NAudio | 2.2.1 | Microphone audio capture |
| Newtonsoft.Json | 13.0.3 | JSON parsing |
| Microsoft.Extensions.Configuration.Abstractions | 10.0.0 | Configuration |
| Microsoft.Extensions.Configuration.UserSecrets | 6.0.1 | Secret management |

### Features
- 16 kHz mono 16-bit PCM audio capture
- WebSocket streaming to Gemini Live
- Transcript and tool call parsing
- RMS volume computation
- Function call handling (`report_intent`)

### Authentication
- API key (environment variable)
- OAuth Bearer token support (via gcloud CLI or service account)

---

## 10. my_google_ai_studio_app

**Description:** React app for Google AI Studio / Gemini Live monitoring

### Core Technologies
- **Language:** TypeScript 5.8+
- **Framework:** React 19.2
- **Build Tool:** Vite 6.2
- **Module System:** ES Modules

### Key Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| react | ^19.2.0 | UI framework |
| react-dom | ^19.2.0 | React DOM |
| @google/genai | ^1.30.0 | Google Generative AI SDK |
| @vitejs/plugin-react | ^5.0.0 | Vite React plugin |

### Features
- Gemini Live monitoring
- Real-time AI interaction
- Modern React with hooks

---

## Technology Summary by Category

### **Languages**
- **Python** (2 repos) - Agent loop, PyTorch
- **C#** (6 repos) - Agent loops, interview assist, audio processing, MCP servers
- **TypeScript** (2 repos) - Agent loop, React UI

### **AI/ML Frameworks**
- **Anthropic Claude API** (3 repos) - Python, .NET, TypeScript agent loops
- **Google Gemini/Generative AI** (2 repos) - Live console, React app
- **OpenAI** (2 repos) - Realtime API, intent detection
- **Azure Cognitive Services Speech** (1 repo) - Speech-to-text
- **Deepgram** (1 repo) - Speech transcription
- **PyTorch** (1 repo) - Deep learning

### **Audio Processing**
- **NAudio** (4 repos) - All C# audio capture projects
- **WASAPI Loopback** (2 repos) - System audio capture
- **Media Foundation** (1 repo) - Audio resampling

### **Web Technologies**
- **WebSocket** (3 repos) - Gemini Live, OpenAI Realtime
- **HTTP/HTTPS** (All repos) - API communication
- **React** (1 repo) - UI framework
- **Vite** (1 repo) - Build tool

### **Google APIs**
- **Gmail API** (3 repos) - Python, .NET, TypeScript
- **Google Calendar API** (3 repos) - Python, .NET, TypeScript
- **Google OAuth2** (3 repos) - Authentication

### **Logging & Configuration**
- **Serilog** (2 repos) - .NET structured logging
- **Loguru** (1 repo) - Python structured logging
- **DotNetEnv** (1 repo) - .NET environment variables
- **python-dotenv** (1 repo) - Python environment variables

### **Testing**
- **xUnit** (3 repos) - C# unit testing
- **Vitest** (1 repo) - TypeScript testing

### **Protocols & Standards**
- **Model Context Protocol (MCP)** (3 repos) - Python, .NET, servers
- **OAuth 2.0** (Multiple repos) - Authentication
- **JSON-RPC** (MCP repos) - Server communication

### **UI Frameworks**
- **.NET MAUI** (1 repo) - Cross-platform desktop
- **Terminal.Gui** (1 repo) - Console TUI
- **React** (1 repo) - Web UI

### **Build & Package Management**
- **uv** (1 repo) - Fast Python package manager
- **pip** (1 repo) - Python packages
- **dotnet CLI** (6 repos) - .NET build system
- **npm** (2 repos) - Node.js packages
- **NuGet** (6 repos) - .NET packages

---

## Common Patterns Across Repositories

### **Architecture Patterns**
1. **Agent Loop Pattern** - 3 implementations (Python, C#, TypeScript)
2. **Real-time Audio Processing** - 4 repos with audio capture/streaming
3. **MCP Tool Servers** - Dynamic tool discovery and integration
4. **Streaming API Integration** - Claude, Gemini, OpenAI Realtime

### **Design Patterns**
- **Observer Pattern** - Event-driven audio/transcript processing
- **Repository Pattern** - Tool registry management
- **Strategy Pattern** - Compaction strategies, search providers
- **Adapter Pattern** - MCP tool proxies
- **Pipeline Pattern** - Audio processing chains

### **Development Practices**
- **Environment-based configuration** - .env files, user secrets
- **Structured logging** - Serilog, Loguru
- **Async/await** - Throughout all projects
- **Dependency injection** - .NET projects
- **Immutable configuration** - Record types, dataclasses
- **Comprehensive documentation** - READMEs, architecture docs, ADRs

---

## Cross-Repository Technology Matrix

| Technology | Python | C# | TypeScript |
|------------|--------|-----|-----------|
| Anthropic Claude | ✓ | ✓ | ✓ |
| Google APIs (Gmail/Calendar) | ✓ | ✓ | ✓ |
| MCP Protocol | ✓ | ✓ | - |
| Audio Processing (NAudio) | - | ✓ | - |
| WebSocket Streaming | - | ✓ | ✓ |
| Async/Concurrent | ✓ (asyncio) | ✓ (Tasks) | ✓ (Promises) |
| Structured Logging | ✓ (Loguru) | ✓ (Serilog) | - |
| OAuth 2.0 | ✓ | ✓ | ✓ |
| LinkedIn API | ✓ | ✓ | ✓ |
| Web Scraping/Parsing | ✓ (BS4) | ✓ (HtmlAgilityPack) | ✓ (Cheerio) |

---

## Notable Technology Choices

### **Python (uv Package Manager)**
- 10-100x faster than pip
- Built-in virtual environment management
- Rust-based for performance
- Used in: micro-x-agent-loop-python

### **.NET 10 (Latest)**
- Used for MCP servers
- MAUI desktop support
- Latest C# features

### **Terminal.Gui**
- Text-based UI for console apps
- Cross-platform TUI framework
- Used in: interview-assist-2

### **Vite**
- Next-generation frontend tooling
- Lightning-fast HMR
- Used in: my_google_ai_studio_app

---

## External Dependencies & APIs

### **Third-Party APIs**
- **Anthropic Claude API** - AI agent capabilities
- **Google Gemini/Generative AI** - Live audio AI
- **OpenAI API** - Realtime API, intent detection
- **Azure Speech Services** - Speech-to-text
- **Deepgram API** - Speech transcription
- **Brave Search API** - Web search
- **LinkedIn Jobs API** - Job search

### **External Tools & Bridges**
- **WhatsApp MCP Server** (Go) - WhatsApp messaging integration
- **gcloud CLI** - OAuth token generation
- **ffmpeg** - Audio format conversion (WhatsApp voice messages)

---

## Development Environment

### **Required Tools**
- Python 3.11+ (for Python repos)
- .NET 8/10 SDK (for C# repos)
- Node.js (for TypeScript repos)
- Git (all repos)

### **Platform Requirements**
- **Windows 10/11** - Required for NAudio-based projects
- **Cross-platform** - Agent loops work on Windows, macOS, Linux

### **IDE/Editor Support**
- Visual Studio / Visual Studio Code
- Rider
- Any text editor with language server support

---

## Summary

Your repository collection demonstrates:

1. **Multi-language expertise** - Python, C#, TypeScript
2. **AI/ML integration** - Multiple AI providers (Claude, Gemini, OpenAI, Azure)
3. **Real-time processing** - Audio streaming, WebSocket communication
4. **Cross-platform development** - .NET MAUI, cross-platform console apps
5. **Modern tooling** - uv, Vite, latest frameworks
6. **Architecture documentation** - Comprehensive READMEs, ADRs, design docs
7. **Production-ready patterns** - Retry logic, logging, error handling, testing
8. **Protocol implementation** - MCP, WebSocket, OAuth 2.0

The repositories show a clear evolution from experimental (torch-playground) to production-quality systems (interview-assist-2) with consistent architectural patterns across implementations.
