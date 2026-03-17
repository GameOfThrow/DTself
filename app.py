"""
Personal Writing Bot — Flask backend
Uses Claude Opus 4.6 with the Memory tool to learn and simulate the user's writing style.
"""

import os
import io
import json
import uuid
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import anthropic

# ── Optional dependencies ────────────────────────────────────────────────────
try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)

TRANSCRIPTS_DIR = "transcripts"
MEMORY_DIR = "memory"
SKILLSETS_DIR = "skillset"

for d in [TRANSCRIPTS_DIR, MEMORY_DIR]:
    os.makedirs(d, exist_ok=True)

# In-process state (single-user personal tool)
conversation_history: list[dict] = []
uploaded_documents: dict[str, dict] = {}
current_session_id: str = str(uuid.uuid4())[:8]
current_transcript: list[dict] = []

MODEL = os.environ.get("BOT_MODEL", "claude-sonnet-4-6")
client = anthropic.Anthropic(max_retries=4)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a personal AI that has been trained to understand, embody, \
and replicate the user's unique writing voice and style. Your primary purpose is to \
write exactly as the user writes — not as a polished AI, but as THEM.

## Your Core Objectives

**1 — Mirror the user's writing style precisely.**
Study every message they send. Notice:
- Vocabulary: do they use casual slang or formal language?
- Sentence structure: short punchy lines or long complex sentences?
- Punctuation habits: em dashes, ellipses, exclamation points?
- Paragraph length: compact blocks or single-line paragraphs?
- Tone: dry, enthusiastic, analytical, conversational?
- Signature phrases or expressions they repeat
Replicate ALL of these in your responses.

**2 — Use your memory tool actively.**
- At the start of each conversation, VIEW your memory files to recall established patterns.
- Store writing style observations in `writing_style.md`.
- Store topic knowledge in `topics.md`.
- Update memory whenever you learn something new about how the user writes or what they know.
- Your memory persists across sessions — build it up over time.

**3 — Draw from uploaded documents.**
When documents are provided, treat them as the user's personal knowledge base. Use their \
terminology, incorporate their ideas, and write in the same spirit as those documents.

**4 — Respond as the user, not as an AI assistant.**
- Avoid AI filler phrases ("Certainly!", "Great question!", "Of course!")
- Don't explain that you're mimicking them — just DO it
- When asked to draft something, write it exactly as they would write it
- Match their level of directness and brevity (or verbosity)

**5 — Keep responses short and conversational.**
- Default to brief, natural replies — the length of a text message or a quick chat response
- Never pad, over-explain, or list things that don't need listing
- If a topic is complex, summarise the key point and let the user ask for more
- Long answers should be the exception, not the rule
- Match the energy of the message: a one-liner question gets a one-liner answer

Begin every new conversation by reading your memory to restore context about this user."""


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(file_obj, filename: str) -> str:
    """Extract plain text from various file formats."""
    ext = os.path.splitext(filename)[1].lower()

    try:
        if ext in {".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
                   ".css", ".html", ".htm", ".json", ".xml", ".csv",
                   ".yaml", ".yml", ".toml", ".sh", ".bat", ".log"}:
            return file_obj.read().decode("utf-8", errors="replace")

        elif ext == ".pdf":
            if not HAS_PDF:
                return (
                    f"[PDF support unavailable. Run: pip install pdfplumber]\n"
                    f"File: {filename}"
                )
            raw = file_obj.read()
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = []
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text and text.strip():
                        pages.append(f"[Page {i}]\n{text.strip()}")
                return "\n\n".join(pages) if pages else "[PDF contained no extractable text]"

        elif ext in {".docx"}:
            if not HAS_DOCX:
                return (
                    f"[DOCX support unavailable. Run: pip install python-docx]\n"
                    f"File: {filename}"
                )
            raw = file_obj.read()
            doc = DocxDocument(io.BytesIO(raw))
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paras)

        else:
            # Attempt generic UTF-8 read
            return file_obj.read().decode("utf-8", errors="replace")

    except Exception as e:
        return f"[Error reading {filename}: {e}]"


# ── Memory tool handler ───────────────────────────────────────────────────────

def handle_memory(tool_input: dict) -> str:
    """
    Execute memory tool commands against the local ./memory/ directory.
    Commands: view | create | str_replace | insert | delete | rename
    """
    command = tool_input.get("command", "view")
    path = tool_input.get("path", "memories.md")

    # Security: prevent directory traversal
    safe_name = os.path.basename(path.lstrip("/\\"))
    if not safe_name or ".." in safe_name:
        return "Error: invalid path"

    safe_path = os.path.join(MEMORY_DIR, safe_name)

    try:
        if command == "view":
            if not os.path.exists(safe_path):
                # List available files instead
                files = [
                    f for f in os.listdir(MEMORY_DIR)
                    if os.path.isfile(os.path.join(MEMORY_DIR, f))
                ]
                if not files:
                    return "(memory is empty — no files yet)"
                return "Memory files available:\n" + "\n".join(f"- {f}" for f in files)
            with open(safe_path, "r", encoding="utf-8") as fh:
                return fh.read()

        elif command == "create":
            file_text = tool_input.get("file_text", tool_input.get("content", ""))
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(file_text)
            return f"Created {safe_name}"

        elif command == "str_replace":
            if not os.path.exists(safe_path):
                return f"Error: {safe_name} not found"
            with open(safe_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            old_str = tool_input.get("old_str", "")
            new_str = tool_input.get("new_str", "")
            if old_str and old_str not in content:
                return f"Error: old_str not found in {safe_name}"
            new_content = content.replace(old_str, new_str, 1) if old_str else content + "\n" + new_str
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            return f"Updated {safe_name}"

        elif command == "insert":
            if not os.path.exists(safe_path):
                return f"Error: {safe_name} not found"
            with open(safe_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            insert_line = int(tool_input.get("insert_line", len(lines)))
            new_str = tool_input.get("new_str", "")
            lines.insert(insert_line, new_str + "\n")
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            return f"Inserted into {safe_name} at line {insert_line}"

        elif command == "delete":
            if not os.path.exists(safe_path):
                return f"Error: {safe_name} not found"
            start = tool_input.get("start_line")
            end = tool_input.get("end_line")
            if start is not None:
                with open(safe_path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
                s = int(start)
                e = int(end) if end is not None else s + 1
                del lines[s:e]
                with open(safe_path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
                return f"Deleted lines {s}–{e} from {safe_name}"
            else:
                os.remove(safe_path)
                return f"Deleted {safe_name}"

        elif command == "rename":
            new_p = tool_input.get("new_path", "")
            new_safe = os.path.basename(new_p.lstrip("/\\"))
            if not new_safe or ".." in new_safe:
                return "Error: invalid new_path"
            if not os.path.exists(safe_path):
                return f"Error: {safe_name} not found"
            os.rename(safe_path, os.path.join(MEMORY_DIR, new_safe))
            return f"Renamed {safe_name} → {new_safe}"

        else:
            return f"Unknown memory command: {command}"

    except Exception as e:
        return f"Memory error: {e}"


# ── Skillset loader ───────────────────────────────────────────────────────────

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse simple YAML-style frontmatter from a markdown file.
    Returns (meta_dict, body_str).
    """
    meta: dict = {}
    if not content.startswith("---"):
        return meta, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return meta, content

    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip("\"'")

    return meta, parts[2].strip()


def load_skillset(key: str) -> dict | None:
    """Load and parse a single skillset file by its key (filename sans .md).
    Returns a dict with id, name, icon, color, tag, description, prompt — or None.
    """
    path = os.path.join(SKILLSETS_DIR, f"{key}.md")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        meta, body = _parse_frontmatter(raw)
        return {
            "id": key,
            "name": meta.get("name", key.title()),
            "icon": meta.get("icon", "💬"),
            "color": meta.get("color", "#6c63ff"),
            "tag": meta.get("tag", key.title()),
            "description": meta.get("description", ""),
            "prompt": body,
        }
    except Exception:
        return None


def list_skillsets() -> list[dict]:
    """Return metadata for all skillsets (no prompt body) in alphabetical order."""
    if not os.path.exists(SKILLSETS_DIR):
        return []
    results = []
    for fname in sorted(os.listdir(SKILLSETS_DIR)):
        if fname.endswith(".md"):
            key = fname[:-3]
            sk = load_skillset(key)
            if sk:
                results.append({k: sk[k] for k in ("id", "name", "icon", "color", "tag", "description")})
    return results


# ── System prompt builder ─────────────────────────────────────────────────────

def build_system(skillset_key: str | None = None) -> str:
    system = SYSTEM_PROMPT

    if uploaded_documents:
        system += "\n\n---\n\n## USER'S KNOWLEDGE BASE (Uploaded Documents)\n\n"
        system += "Use the content and style of these documents when relevant:\n\n"
        for doc in uploaded_documents.values():
            preview = doc["content"]
            if len(preview) > 10_000:
                preview = preview[:10_000] + f"\n\n[...truncated — full length {len(doc['content'])} chars]"
            system += f"### {doc['name']}\n\n{preview}\n\n"

    if skillset_key:
        sk = load_skillset(skillset_key)
        if sk:
            system += (
                f"\n\n---\n\n"
                f"## ACTIVE EMOTION MODE: {sk['name'].upper()} {sk['icon']}\n\n"
                f"{sk['prompt']}\n\n"
                f"**CRITICAL**: Apply the above emotional rewriting instructions to every response you "
                f"generate in this conversation. The user's writing style is still the foundation — but "
                f"it must now be expressed through the emotional lens described above."
            )

    return system


# ── Transcript helper ─────────────────────────────────────────────────────────

def save_transcript():
    path = os.path.join(TRANSCRIPTS_DIR, f"session_{current_session_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "session_id": current_session_id,
                "timestamp": datetime.now().isoformat(),
                "messages": current_transcript,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", model=MODEL)


@app.route("/api/chat", methods=["POST"])
def chat():
    global conversation_history, current_session_id, current_transcript

    data = request.json or {}
    user_message = data.get("message", "").strip()
    active_skillset = data.get("skillset") or None  # e.g. "angry", "sad", "happy", "productive"
    active_model = data.get("model") or MODEL
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    conversation_history.append({"role": "user", "content": user_message})
    current_transcript.append(
        {
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now().isoformat(),
            "skillset": active_skillset,
        }
    )

    def generate():
        global conversation_history, current_transcript

        system = build_system(skillset_key=active_skillset)
        messages = list(conversation_history)

        # Emit emotion mode info as first event so the frontend can badge the bubble
        if active_skillset:
            sk = load_skillset(active_skillset)
            if sk:
                yield f"data: {json.dumps({'type': 'mode', 'id': sk['id'], 'name': sk['name'], 'icon': sk['icon'], 'color': sk['color']})}\n\n"
        full_response = ""

        try:
            max_iterations = 10
            for iteration in range(max_iterations):
                with client.messages.stream(
                    model=active_model,
                    max_tokens=4096,
                    system=system,
                    messages=messages,
                    tools=[{
                        "name": "memory",
                        "description": (
                            "Read and write persistent memory files to store observations about "
                            "the user's writing style, vocabulary, tone, preferences, and topic knowledge. "
                            "Use this to build and update a profile across sessions. "
                            "Files are stored in the ./memory/ directory."
                        ),
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "enum": ["view", "create", "str_replace", "insert", "delete", "rename"],
                                    "description": "Operation to perform on memory files.",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Filename within the memory directory, e.g. 'writing_style.md' or 'topics.md'.",
                                },
                                "file_text": {
                                    "type": "string",
                                    "description": "Full content to write when using the create command.",
                                },
                                "old_str": {
                                    "type": "string",
                                    "description": "Exact string to find and replace (str_replace command).",
                                },
                                "new_str": {
                                    "type": "string",
                                    "description": "Replacement string for str_replace, or text to insert for insert command.",
                                },
                                "insert_line": {
                                    "type": "integer",
                                    "description": "Line index at which to insert new_str (insert command).",
                                },
                                "start_line": {
                                    "type": "integer",
                                    "description": "First line index to delete (delete command). Omit to delete the whole file.",
                                },
                                "end_line": {
                                    "type": "integer",
                                    "description": "Last line index to delete, exclusive (delete command).",
                                },
                                "new_path": {
                                    "type": "string",
                                    "description": "New filename for the rename command.",
                                },
                            },
                            "required": ["command", "path"],
                        },
                    }],
                ) as stream:
                    for event in stream:
                        # Signal when memory tool is invoked
                        if (
                            event.type == "content_block_start"
                            and hasattr(event, "content_block")
                            and event.content_block.type == "tool_use"
                        ):
                            yield (
                                f"data: {json.dumps({'type': 'tool_start', 'name': event.content_block.name})}\n\n"
                            )

                        # Stream text deltas to the browser
                        elif (
                            event.type == "content_block_delta"
                            and hasattr(event, "delta")
                            and event.delta.type == "text_delta"
                        ):
                            chunk = event.delta.text
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

                    final = stream.get_final_message()

                # Done — no more tool calls
                if final.stop_reason == "end_turn":
                    break

                # Handle memory tool calls, then loop
                if final.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": final.content})
                    tool_results = []

                    for block in final.content:
                        if block.type == "tool_use":
                            result = handle_memory(dict(block.input))
                            cmd = block.input.get("command", "?")
                            yield (
                                f"data: {json.dumps({'type': 'tool_done', 'cmd': cmd, 'result': result[:120]})}\n\n"
                            )
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result,
                                }
                            )

                    messages.append({"role": "user", "content": tool_results})
                else:
                    break

        except anthropic.AuthenticationError:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Invalid API key. Set the ANTHROPIC_API_KEY environment variable.'})}\n\n"
            return
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
            return

        # Persist to history and transcript
        if full_response:
            conversation_history.append({"role": "assistant", "content": full_response})
            current_transcript.append(
                {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.now().isoformat(),
                    "skillset": active_skillset,
                }
            )

        save_transcript()
        yield f"data: {json.dumps({'type': 'done', 'session_id': current_session_id})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/skillsets", methods=["GET"])
def get_skillsets():
    """Return list of available emotion skillsets (reloads from disk each call)."""
    return jsonify(list_skillsets())


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    doc_id = str(uuid.uuid4())[:8]
    filename = file.filename
    content = extract_text(file, filename)

    uploaded_documents[doc_id] = {
        "id": doc_id,
        "name": filename,
        "content": content,
        "chars": len(content),
        "uploaded_at": datetime.now().isoformat(),
    }

    return jsonify(
        {
            "id": doc_id,
            "name": filename,
            "chars": len(content),
            "preview": content[:300] + ("…" if len(content) > 300 else ""),
        }
    )


@app.route("/api/documents", methods=["GET"])
def get_documents():
    return jsonify(
        [
            {
                "id": d["id"],
                "name": d["name"],
                "chars": d["chars"],
                "uploaded_at": d["uploaded_at"],
            }
            for d in uploaded_documents.values()
        ]
    )


@app.route("/api/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id: str):
    if doc_id in uploaded_documents:
        del uploaded_documents[doc_id]
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


@app.route("/api/memory", methods=["GET"])
def get_memory():
    result: dict[str, str] = {}
    try:
        for fname in sorted(os.listdir(MEMORY_DIR)):
            fpath = os.path.join(MEMORY_DIR, fname)
            if os.path.isfile(fpath):
                with open(fpath, "r", encoding="utf-8") as fh:
                    result[fname] = fh.read()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(result)


@app.route("/api/transcripts", methods=["GET"])
def get_transcripts():
    result = []
    try:
        for fname in sorted(os.listdir(TRANSCRIPTS_DIR), reverse=True):
            if fname.endswith(".json"):
                fpath = os.path.join(TRANSCRIPTS_DIR, fname)
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                result.append(
                    {
                        "session_id": data.get("session_id"),
                        "timestamp": data.get("timestamp"),
                        "messages": len(data.get("messages", [])),
                        "file": fname,
                    }
                )
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/clear", methods=["POST"])
def clear():
    global conversation_history, current_session_id, current_transcript
    conversation_history = []
    current_session_id = str(uuid.uuid4())[:8]
    current_transcript = []
    return jsonify({"ok": True, "session_id": current_session_id})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Writing Bot  ->  http://localhost:{port}")
    print(f"  Transcripts  ->  ./{TRANSCRIPTS_DIR}/")
    print(f"  Memory       ->  ./{MEMORY_DIR}/")
    print(f"\n   Ensure ANTHROPIC_API_KEY is set in your environment.\n")
    app.run(debug=True, port=port, threaded=True)
