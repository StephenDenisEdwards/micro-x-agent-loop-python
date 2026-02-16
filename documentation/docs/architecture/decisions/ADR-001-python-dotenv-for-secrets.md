# ADR-001: python-dotenv for Secrets Management

## Status

Accepted

## Context

The application requires API keys for Anthropic and Google OAuth credentials. These secrets must not be committed to source control. Python offers several options for secret management:

1. **Environment variables** — set at OS level, no file needed
2. **python-dotenv** (`.env` file) — simple file-based approach, widely used in the Python ecosystem
3. **python-decouple** — similar to dotenv with type casting, less popular
4. **Cloud secret managers** (AWS Secrets Manager, Azure Key Vault) — production-grade, overkill for this use case

The sibling `micro-x-agent-loop-dotnet` project uses a `.env` file with the `DotNetEnv` package. Keeping the same `.env` file format allows sharing credentials between both projects without reconfiguration.

## Decision

Use the `python-dotenv` package to load secrets from a `.env` file at startup via `load_dotenv()`. The `.env` file is added to `.gitignore` to prevent accidental commits.

Non-secret configuration (model, max tokens, temperature, paths) lives separately in `config.json`.

## Consequences

**Easier:**
- Share the same `.env` file between the .NET and Python versions
- Simple to set up — just create a file, no tooling required
- Familiar pattern — python-dotenv is the de facto standard in the Python ecosystem
- `load_dotenv()` merges `.env` values into `os.environ` seamlessly

**Harder:**
- No built-in rotation or encryption (acceptable for personal/development use)
- Must remember to create `.env` manually on new machines
- Not suitable for production deployment without additional secret management
