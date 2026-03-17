# Writing Bot — Personal Style AI

A personal chatbot that learns and simulates your writing style, powered by Claude Opus 4.6.

## Features

- **Style simulation** — Claude studies how you write and mirrors your exact voice
- **Document upload** — Drop PDFs, DOCX, TXT, Markdown, code files and more; extracted text becomes the bot's knowledge base
- **Persistent memory** — The bot stores observations about your style in `./memory/` files that survive across sessions
- **Streaming chat** — Real-time token streaming so responses appear as they're generated
- **Auto transcripts** — Every session is saved to `./transcripts/session_<id>.json`

## Quick Start

### 1. Set your API key

```bash
# Windows
set ANTHROPIC_API_KEY=sk-ant-...

# macOS/Linux
export ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

Then open **http://localhost:5000** in your browser.

On Windows you can also double-click **`start.bat`** — it creates a venv and installs deps automatically.

---

## Supported File Formats

| Extension | Notes |
|-----------|-------|
| `.txt` `.md` `.log` | Plain text, direct read |
| `.pdf` | Requires `pdfplumber` (included) |
| `.docx` | Requires `python-docx` (included) |
| `.py` `.js` `.ts` `.jsx` `.tsx` | Source code |
| `.json` `.yaml` `.toml` | Config / data |
| `.csv` `.html` `.xml` | Structured data |

---

## Project Structure

```
DTself/
├── app.py              ← Flask backend + Claude API
├── requirements.txt
├── start.bat           ← Windows one-click launcher
├── templates/
│   └── index.html      ← Single-page frontend
├── memory/             ← Bot's persistent style notes (auto-created)
│   ├── writing_style.md
│   └── topics.md
└── transcripts/        ← Session transcripts (auto-created)
    └── session_<id>.json
```

---

## How the Memory Works

The bot uses Claude's built-in `memory` tool with the `context-management-2025-06-27` beta. When Claude decides to remember something (e.g., "user writes in short paragraphs, avoids passive voice"), it calls the memory tool to write/update files in `./memory/`. These files are loaded back on subsequent sessions.

You can view memory files at any time via the **Memory** button in the UI, or read the files directly in `./memory/`.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `PORT` | `5000` | Port to run the server on |
