"""
Agent-based form filling using DeepSeek (OpenAI-compatible API).

Uses OpenAI SDK with function calling to implement a form-filling agent.

This module provides the same interface as the original agent version,
but uses DeepSeek LLM instead.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    # Load .env file from project root (one level up from backend)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

try:
    from openai import OpenAI, AsyncOpenAI
    OPENAI_SDK_AVAILABLE = True
except ImportError as e:
    OPENAI_SDK_AVAILABLE = False
    print(f"[Agent] OpenAI SDK not available: {e}")
    print("[Agent] Install with: pip install openai")

# Import PDF processing
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from pdf_processor import detect_form_fields, DetectedField, FieldType

# ============================================================================
# Session Management (copied from agent.py to avoid circular imports)
# ============================================================================

import threading
import uuid
import sqlite3
import time
from contextvars import ContextVar
from pathlib import Path as PathlibPath

class FormFillingSession:
    """Holds state for a form-filling session."""
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.doc = None
        self.pdf_path: str | None = None
        self.output_path: str | None = None
        self.fields: list[DetectedField] = []
        self.pending_edits: dict[str, Any] = {}
        self.applied_edits: dict[str, Any] = {}
        self.current_pdf_bytes: bytes | None = None
        self.original_pdf_bytes: bytes | None = None
        self.is_continuation: bool = False
        self.context_files: list = []

    def reset(self):
        """Reset session state for a new form filling operation."""
        if self.doc:
            self.doc.close()
        self.doc = None
        self.pdf_path = None
        self.output_path = None
        self.fields = []
        self.pending_edits = {}
        self.applied_edits = {}
        self.current_pdf_bytes = None
        self.original_pdf_bytes = None
        self.is_continuation = False

    def soft_reset(self):
        """Reset for a new turn but preserve the filled PDF state."""
        self.pending_edits = {}


# Database path
_DB_PATH = PathlibPath(__file__).parent / "sessions.db"
_SESSIONS_DATA_DIR = PathlibPath(__file__).parent / "sessions_data"


class SessionManager:
    """Thread-safe manager for multiple concurrent user sessions with SQLite persistence."""
    def __init__(self, db_path: str | PathlibPath | None = None, data_dir: str | PathlibPath | None = None):
        self._sessions: dict[str, FormFillingSession] = {}
        self._lock = threading.Lock()
        self._db_path = str(db_path or _DB_PATH)
        self._data_dir = PathlibPath(data_dir or _SESSIONS_DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_sessions_from_db()

    def _init_db(self):
        """Initialize the SQLite database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(sessions)")
            columns = {row[1] for row in cursor.fetchall()}

            if not columns:
                conn.execute("""
                    CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY,
                        pdf_path TEXT,
                        output_path TEXT,
                        applied_edits TEXT,
                        pdf_file_path TEXT,
                        original_pdf_file_path TEXT,
                        context_files TEXT,
                        created_at REAL,
                        updated_at REAL
                    )
                """)
            conn.commit()
        print(f"[SessionManager] Database initialized at: {self._db_path}")

    def _load_sessions_from_db(self):
        """Load existing sessions from the database on startup."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM sessions")
                rows = cursor.fetchall()

                for row in rows:
                    session = FormFillingSession(row['session_id'])
                    session.pdf_path = row['pdf_path']
                    session.output_path = row['output_path']

                    pdf_file_path = row.get('pdf_file_path')
                    if pdf_file_path:
                        file_path = PathlibPath(pdf_file_path)
                        if file_path.exists():
                            session.current_pdf_bytes = file_path.read_bytes()

                    original_pdf_file_path = row.get('original_pdf_file_path')
                    if original_pdf_file_path:
                        file_path = PathlibPath(original_pdf_file_path)
                        if file_path.exists():
                            session.original_pdf_bytes = file_path.read_bytes()

                    if row.get('applied_edits'):
                        try:
                            session.applied_edits = json.loads(row['applied_edits'])
                        except json.JSONDecodeError:
                            session.applied_edits = {}

                    context_files_json = row.get('context_files')
                    if context_files_json:
                        try:
                            session.context_files = json.loads(context_files_json)
                        except json.JSONDecodeError:
                            session.context_files = []

                    self._sessions[session.session_id] = session

                print(f"[SessionManager] Loaded {len(rows)} sessions from database")
        except Exception as e:
            print(f"[SessionManager] Error loading sessions: {e}")

    def _save_session_to_db(self, session: FormFillingSession):
        """Save a session to the database."""
        try:
            pdf_file_path = None
            if session.current_pdf_bytes:
                pdf_file_path = self._data_dir / f"{session.session_id}.pdf"
                pdf_file_path.write_bytes(session.current_pdf_bytes)
                pdf_file_path = str(pdf_file_path)

            original_pdf_file_path = None
            if session.original_pdf_bytes:
                original_pdf_file_path = self._data_dir / f"{session.session_id}_original.pdf"
                original_pdf_file_path.write_bytes(session.original_pdf_bytes)
                original_pdf_file_path = str(original_pdf_file_path)

            context_files_json = None
            if session.context_files:
                context_files_data = []
                for cf in session.context_files:
                    if hasattr(cf, 'to_dict'):
                        context_files_data.append(cf.to_dict())
                    elif isinstance(cf, dict):
                        context_files_data.append(cf)
                    else:
                        context_files_data.append({
                            "filename": getattr(cf, 'filename', 'unknown'),
                            "content": getattr(cf, 'content', ''),
                            "was_parsed": getattr(cf, 'was_parsed', False)
                        })
                context_files_json = json.dumps(context_files_data)

            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sessions
                    (session_id, pdf_path, output_path, applied_edits, pdf_file_path, original_pdf_file_path, context_files, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM sessions WHERE session_id = ?), ?), ?)
                """, (
                    session.session_id,
                    session.pdf_path,
                    session.output_path,
                    json.dumps(session.applied_edits) if session.applied_edits else None,
                    pdf_file_path,
                    original_pdf_file_path,
                    context_files_json,
                    session.session_id,
                    time.time(),
                    time.time(),
                ))
                conn.commit()
        except Exception as e:
            print(f"[SessionManager] Error saving session {session.session_id}: {e}")

    def get_or_create_session(self, session_id: str | None = None) -> FormFillingSession:
        """Get existing session or create a new one."""
        if session_id:
            with self._lock:
                if session_id in self._sessions:
                    return self._sessions[session_id]
        
        session = FormFillingSession(session_id)
        with self._lock:
            self._sessions[session.session_id] = session
        self._save_session_to_db(session)
        return session

    def get_session(self, session_id: str) -> FormFillingSession | None:
        """Get an existing session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def save_session(self, session: FormFillingSession):
        """Explicitly save session state to database."""
        self._save_session_to_db(session)

    def get_session_pdf_bytes(self, session_id: str) -> bytes | None:
        """Get the filled PDF bytes for a session."""
        session = self.get_session(session_id)
        if session and session.current_pdf_bytes:
            return session.current_pdf_bytes
        return None

    def get_session_original_pdf_bytes(self, session_id: str) -> bytes | None:
        """Get the original (unfilled) PDF bytes for a session."""
        session = self.get_session(session_id)
        if session and session.original_pdf_bytes:
            return session.original_pdf_bytes
        return None

    def get_session_context_files(self, session_id: str) -> list | None:
        """Get the context files for a session."""
        session = self.get_session(session_id)
        if session and session.context_files:
            return session.context_files
        return None

    def cleanup_old_sessions(self, max_age_seconds: int = 3600):
        """Clean up sessions older than max_age_seconds."""
        cutoff_time = time.time() - max_age_seconds
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "SELECT session_id FROM sessions WHERE updated_at < ?",
                    (cutoff_time,)
                )
                old_sessions = [row[0] for row in cursor.fetchall()]

                for sid in old_sessions:
                    pdf_file_path = self._data_dir / f"{sid}.pdf"
                    if pdf_file_path.exists():
                        pdf_file_path.unlink()
                    original_pdf_file_path = self._data_dir / f"{sid}_original.pdf"
                    if original_pdf_file_path.exists():
                        original_pdf_file_path.unlink()

                conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ?",
                    (cutoff_time,)
                )
                conn.commit()

                with self._lock:
                    for sid in old_sessions:
                        if sid in self._sessions:
                            self._sessions[sid].reset()
                            del self._sessions[sid]

                if old_sessions:
                    print(f"[SessionManager] Cleaned up {len(old_sessions)} old sessions")
        except Exception as e:
            print(f"[SessionManager] Error during cleanup: {e}")


# Global session manager
_session_manager = SessionManager()

# Context variable for current session
_current_session: ContextVar[FormFillingSession | None] = ContextVar('current_session', default=None)


def get_current_session() -> FormFillingSession | None:
    """Get the current session from context."""
    return _current_session.get()


def set_current_session(session: FormFillingSession | None):
    """Set the current session in context."""
    _current_session.set(session)


# ============================================================================
# Tool Definitions (OpenAI Function Calling Format)
# ============================================================================

FORM_FILLING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "load_pdf",
            "description": "Load a PDF file and detect its form fields. This must be called first before any other operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file to load"
                    }
                },
                "required": ["pdf_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_fields",
            "description": "List all form fields in the loaded PDF. Returns field IDs, types, labels, and current values.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_fields",
            "description": "Search for form fields matching a query string. Useful for finding fields by label or context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to match against field labels or context"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_field_details",
            "description": "Get detailed information about a specific form field, including its type, label, options, and current value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_id": {
                        "type": "string",
                        "description": "The field_id of the field to get details for"
                    }
                },
                "required": ["field_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_field",
            "description": "Stage a value for a form field. This does not apply the edit yet - call commit_edits to apply all staged edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_id": {
                        "type": "string",
                        "description": "The field_id of the field to set"
                    },
                    "value": {
                        "type": "string",
                        "description": "The value to set. For checkboxes, use 'true' or 'false' as strings."
                    }
                },
                "required": ["field_id", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_edits",
            "description": "Review all staged edits before committing. Returns a list of all fields that have been staged for editing.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "commit_edits",
            "description": "Apply all staged edits and save the filled PDF to the output path. This is the final step after setting all field values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "Path to save the filled PDF (optional, uses default if not provided)"
                    }
                },
                "required": []
            }
        }
    }
]


# ============================================================================
# Tool Implementation Functions
# ============================================================================

async def tool_load_pdf(pdf_path: str, session: FormFillingSession) -> dict[str, Any]:
    """Load a PDF and detect its form fields."""
    print(f"[load_pdf] Loading: {pdf_path} (session: {session.session_id})")
    try:
        session.doc = fitz.open(pdf_path)
        session.pdf_path = pdf_path

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        session.fields = detect_form_fields(pdf_bytes)
        session.pending_edits = {}
        # Don't clear applied_edits if this is a continuation
        if not session.is_continuation:
            session.applied_edits = {}

        result = {
            "success": True,
            "message": f"Loaded PDF with {len(session.fields)} form fields",
            "field_count": len(session.fields)
        }
        print(f"[load_pdf] Success: {len(session.fields)} fields found")
        return result
    except Exception as e:
        result = {"success": False, "error": str(e)}
        print(f"[load_pdf] Error: {e}")
        return result


async def tool_list_all_fields(session: FormFillingSession) -> dict[str, Any]:
    """List all detected form fields."""
    if not session or not session.doc:
        return {"error": "No PDF loaded. Call load_pdf first."}

    fields = []
    for f in session.fields:
        field_info = {
            "field_id": f.field_id,
            "type": f.field_type.value,
            "page": f.page,
            "label": f.friendly_label or f.label_context[:100],
            "has_options": f.options is not None,
        }
        # Include current value if the field has been filled
        if f.field_id in session.applied_edits:
            field_info["current_value"] = session.applied_edits[f.field_id]
        elif f.current_value:
            field_info["current_value"] = f.current_value
        fields.append(field_info)

    return {"fields": fields, "count": len(fields)}


async def tool_search_fields(query: str, session: FormFillingSession) -> dict[str, Any]:
    """Search fields by label context."""
    if not session or not session.doc:
        return {"error": "No PDF loaded."}

    query_lower = query.lower()
    results = []

    for f in session.fields:
        # Search in both friendly_label and label_context
        friendly_lower = (f.friendly_label or "").lower()
        context_lower = f.label_context.lower()
        if query_lower in friendly_lower or query_lower in context_lower or any(word in friendly_lower or word in context_lower for word in query_lower.split()):
            field_info = {
                "field_id": f.field_id,
                "type": f.field_type.value,
                "page": f.page,
                "label": f.friendly_label or f.label_context[:150],
                "options": f.options,
            }
            # Include current value if set
            if f.field_id in session.applied_edits:
                field_info["current_value"] = session.applied_edits[f.field_id]
            results.append(field_info)

    return {"results": results[:10], "count": len(results)}


async def tool_get_field_details(field_id: str, session: FormFillingSession) -> dict[str, Any]:
    """Get full details about a field."""
    if not session or not session.doc:
        return {"error": "No PDF loaded."}

    field = next((f for f in session.fields if f.field_id == field_id), None)

    if not field:
        return {"error": f"Field not found: {field_id}"}

    result = {
        "field_id": field.field_id,
        "type": field.field_type.value,
        "page": field.page,
        "label": field.friendly_label or field.label_context,
        "options": field.options,
        "pending_value": session.pending_edits.get(field_id),
        "current_value": session.applied_edits.get(field_id) or field.current_value,
    }
    return result


async def tool_set_field(field_id: str, value: str, session: FormFillingSession) -> dict[str, Any]:
    """Stage a field edit."""
    print(f"[set_field] Called with: field_id={field_id}, value={value}")
    if not session or not session.doc:
        return {"error": "No PDF loaded."}

    field = next((f for f in session.fields if f.field_id == field_id), None)
    if not field:
        print(f"[set_field] Field not found: {field_id}")
        return {"error": f"Field not found: {field_id}"}

    # Handle boolean for checkboxes
    if field.field_type == FieldType.CHECKBOX:
        if isinstance(value, str):
            value = value.lower() in ('true', 'yes', '1', 'checked')

    session.pending_edits[field_id] = value
    print(f"[set_field] Staged: {field_id} = {value} (total pending: {len(session.pending_edits)})")

    result = {
        "success": True,
        "field_id": field_id,
        "value": value,
        "pending_count": len(session.pending_edits)
    }
    return result


async def tool_get_pending_edits(session: FormFillingSession) -> dict[str, Any]:
    """Get all pending edits."""
    if not session:
        return {"error": "No active session"}

    edits = []
    for field_id, value in session.pending_edits.items():
        field = next((f for f in session.fields if f.field_id == field_id), None)
        edits.append({
            "field_id": field_id,
            "value": value,
            "label": (field.friendly_label or field.label_context[:80]) if field else "unknown",
            "type": field.field_type.value if field else "unknown",
        })

    return {"pending_edits": edits, "count": len(edits)}


async def tool_commit_edits(output_path: Optional[str], session: FormFillingSession) -> dict[str, Any]:
    """Apply edits and save."""
    print(f"[commit_edits] Called with output_path: {output_path}")
    if not session:
        return {"error": "No active session"}

    print(f"[commit_edits] Session output_path: {session.output_path}")
    print(f"[commit_edits] Pending edits: {len(session.pending_edits)}")

    if not session.doc:
        return {"error": "No PDF loaded."}

    output_path = output_path or session.output_path
    if not output_path:
        output_path = session.pdf_path.replace('.pdf', '_filled.pdf') if session.pdf_path else 'filled.pdf'

    print(f"[commit_edits] Saving to: {output_path}")

    applied = []
    errors = []

    for field_id, value in session.pending_edits.items():
        field = next((f for f in session.fields if f.field_id == field_id), None)
        if not field:
            errors.append(f"Field not found: {field_id}")
            continue

        try:
            page = session.doc[field.page]
            for widget in page.widgets():
                widget_field_id = f"page{field.page}_{widget.field_name}"
                if widget_field_id == field_id:
                    if field.field_type == FieldType.CHECKBOX:
                        widget.field_value = bool(value)
                    else:
                        widget.field_value = str(value)
                    widget.update()
                    applied.append({"field_id": field_id, "value": value})
                    session.applied_edits[field_id] = value
                    print(f"[commit_edits] Applied: {field_id} = {value}")
                    break
        except Exception as e:
            errors.append(f"Failed to apply {field_id}: {str(e)}")
            print(f"[commit_edits] Error: {e}")

    # Save
    try:
        session.doc.save(output_path)
        print(f"[commit_edits] Saved successfully to: {output_path}")

        # Store the filled PDF bytes for multi-turn
        with open(output_path, 'rb') as f:
            session.current_pdf_bytes = f.read()

        # Verify file was created
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"[commit_edits] File verified: {file_size} bytes")
        else:
            print(f"[commit_edits] WARNING: File not found after save!")
            errors.append("File not created after save")
        
        # Close the document to release file lock (important for Windows)
        session.doc.close()
        session.doc = None
    except Exception as e:
        print(f"[commit_edits] Save error: {e}")
        errors.append(f"Save failed: {str(e)}")

    session.pending_edits.clear()

    result = {
        "success": len(errors) == 0,
        "applied": applied,
        "applied_count": len(applied),
        "total_fields_filled": len(session.applied_edits),
        "errors": errors,
        "output_path": output_path
    }
    print(f"[commit_edits] Result: {result}")
    return result


# Tool execution dispatcher
async def execute_tool(tool_name: str, arguments: dict[str, Any], session: FormFillingSession) -> dict[str, Any]:
    """Execute a tool function by name."""
    if tool_name == "load_pdf":
        return await tool_load_pdf(arguments.get("pdf_path", ""), session)
    elif tool_name == "list_all_fields":
        return await tool_list_all_fields(session)
    elif tool_name == "search_fields":
        return await tool_search_fields(arguments.get("query", ""), session)
    elif tool_name == "get_field_details":
        return await tool_get_field_details(arguments.get("field_id", ""), session)
    elif tool_name == "set_field":
        return await tool_set_field(arguments.get("field_id", ""), arguments.get("value", ""), session)
    elif tool_name == "get_pending_edits":
        return await tool_get_pending_edits(session)
    elif tool_name == "commit_edits":
        return await tool_commit_edits(arguments.get("output_path"), session)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ============================================================================
# Agent Implementation using DeepSeek
# ============================================================================

def get_deepseek_client() -> AsyncOpenAI:
    """Get DeepSeek API client."""
    import httpx
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY environment variable is required. "
            "Set it with: export DEEPSEEK_API_KEY=your-key-here"
        )
    
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    
    # Create client without proxy to avoid conflicts with system proxy settings
    http_client = httpx.AsyncClient(proxy=None)
    return AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


SYSTEM_PROMPT = """You are a form-filling agent. Your job is to fill out PDF forms based on user instructions.

## Available Tools:
- load_pdf: Load a PDF file (MUST be called first)
- list_all_fields: See all form fields (includes current values if already filled)
- search_fields: Find fields matching a query
- get_field_details: Get details about a specific field
- set_field: Stage a value for a field (can be called multiple times in parallel)
- get_pending_edits: Review staged edits before committing
- commit_edits: Apply all edits and save (final step)

## Workflow:
1. Call load_pdf with the PDF path
2. Call list_all_fields to see ALL fields - READ THE FULL LIST CAREFULLY
3. For EACH piece of information the user provides:
   a. Find the EXACT matching field from the list (use field_id exactly as shown)
   b. Call set_field with the correct field_id and value
4. Call get_pending_edits to review
5. Call commit_edits with the output path to save

## CRITICAL - Field Matching:
- ALWAYS call list_all_fields first and READ THE ENTIRE LIST
- Match user information to field labels carefully:
  - "name" -> fields with "Name" in label (e.g., "Name as shown on your income tax return")
  - "address", "street", "living on" -> fields with "Address" in label (e.g., "Address (number, street, and apt. or suite no.)")
  - "city" -> fields with "City" in label
  - "SSN", "social security" -> fields with "Social security number" or "SSN"
- Use the EXACT field_id from list_all_fields, not a made-up one
- If user says "I am living on 303 Napoleon Street", that's the ADDRESS - fill the Address field

## CRITICAL - DO NOT CONFUSE THESE FIELD TYPES:
- "Exempt payee code" = a NUMERIC CODE (1-13), NOT an address!
- "FATCA code" or "Exemption from FATCA reporting code" = a LETTER CODE (A-M), NOT an address!
- "Address" fields typically say "Address", "street", "number" in their label
- When user provides an address like "303 Napoleon Street, Southbend, Indiana":
  - Fill the "Address" field with the street address (e.g., "303 Napoleon Street")
  - Fill the "City, state, and ZIP code" field with city/state/zip
  - NEVER fill code fields (Exempt payee code, FATCA code) with address information!

## IMPORTANT - Parallel Tool Use:
For maximum efficiency, when you need to set multiple fields, call set_field for ALL of them simultaneously in parallel rather than one at a time.

## Multi-Turn Editing:
When continuing from a previous session:
- The PDF path provided is the ALREADY FILLED form from the previous turn
- Fields will show their current_value from previous edits
- Only modify the specific fields the user mentions
- Don't re-fill fields that were already correctly filled unless asked

## Rules:
- For dropdowns, use exact option values
- For checkboxes, use "true" or "false" as strings in set_field (they will be converted to booleans)
- Always review with get_pending_edits before committing
- ALWAYS use parallel tool calls when setting multiple fields
- When continuing, preserve existing values unless explicitly asked to change them

## CRITICAL - Multi-Part Fields (SSN, EIN, Phone, Date):
Forms often split numbers into MULTIPLE SEPARATE FIELDS. You MUST fill EACH part separately!

### SSN (Social Security Number) - 9 digits split into 3 fields:
Format: XXX-XX-XXXX
- Field labels will be like: "SSN Part 1 (3 digits)", "SSN Part 2 (2 digits)", "SSN Part 3 (4 digits)"
- Example: User says "my SSN is 332011932"
  - Call set_field for SSN Part 1 with value "332"
  - Call set_field for SSN Part 2 with value "01"
  - Call set_field for SSN Part 3 with value "1932"
- ALWAYS make 3 separate set_field calls for SSN!

### EIN (Employer Identification Number) - 9 digits split into 2 fields:
Format: XX-XXXXXXX
- Field labels will be like: "EIN Part 1 (2 digits)", "EIN Part 2 (7 digits)"
- Example: User says "my EIN is 231234567"
  - Call set_field for EIN Part 1 with value "23"
  - Call set_field for EIN Part 2 with value "1234567"
- ALWAYS make 2 separate set_field calls for EIN!

### CRITICAL: DO NOT confuse SSN and EIN fields!
- SSN fields are labeled "SSN Part X" - for Social Security Number
- EIN fields are labeled "EIN Part X" - for Employer Identification Number
- They are DIFFERENT fields, even if they are near each other on the form

### Phone numbers: May be split into area code + number
### Dates: May be split into month/day/year fields

ALWAYS call list_all_fields first and look for all parts of multi-part fields!
"""

CONTINUATION_SYSTEM_PROMPT = """You are a form-filling agent continuing a multi-turn conversation.

## Context:
- The user has ALREADY filled out this form in a previous turn
- The PDF you're loading contains the PREVIOUSLY FILLED values
- You should ONLY modify the fields the user specifically asks about
- All other fields should remain unchanged

## Available Tools:
- load_pdf: Load the already-filled PDF
- list_all_fields: See all fields WITH their current values
- search_fields: Find fields matching a query
- get_field_details: Get details about a specific field (shows current value)
- set_field: Stage a new value for a field
- get_pending_edits: Review staged edits
- commit_edits: Apply changes and save

## Workflow for Continuation:
1. Load the PDF (it already has previous values)
2. List fields to see what's currently filled
3. ONLY set_field for the specific fields the user wants to change
4. Review and commit

## CRITICAL:
- Do NOT re-set fields that the user didn't ask to change
- The form already has values - you're making INCREMENTAL updates
- Only modify what the user explicitly requests

## CRITICAL - Multi-Part Fields:
### SSN (9 digits → 3 fields):
- "332011932" → "332" (Part 1), "01" (Part 2), "1932" (Part 3)
- Make 3 separate set_field calls for SSN Part 1, Part 2, Part 3

### EIN (9 digits → 2 fields):
- "231234567" → "23" (Part 1), "1234567" (Part 2)
- Make 2 separate set_field calls for EIN Part 1, Part 2

### DO NOT mix up SSN and EIN fields - they are different!

### Phone/Date: Split similarly if there are separate fields
"""


async def run_agent_stream(
    pdf_path: str,
    instructions: str,
    output_path: str | None = None,
    is_continuation: bool = False,
    previous_edits: dict[str, Any] | None = None,
    resume_session_id: str | None = None,
    user_session_id: str | None = None,
    original_pdf_bytes: bytes | None = None,
    context_files: list | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the agent and yield messages as they come in (for streaming).

    Uses DeepSeek API with function calling for form filling.

    Args:
        pdf_path: Path to the PDF file
        instructions: User's instructions for this turn
        output_path: Where to save the filled PDF
        is_continuation: Whether this is a continuation of a previous session
        previous_edits: Dict of field_id -> value from previous turns
        resume_session_id: Session ID from previous turn (for conversation context)
        user_session_id: Unique ID for this user's form-filling session
        original_pdf_bytes: The original (unfilled) PDF bytes for first-turn sessions
        context_files: List of parsed context files

    Yields:
        dict: Serialized message from the agent
    """
    print(f"[Agent Stream] Starting with pdf_path={pdf_path}, is_continuation={is_continuation}, user_session_id={user_session_id}")

    if not OPENAI_SDK_AVAILABLE:
        yield {"type": "error", "error": "OpenAI SDK not available. Install with: pip install openai"}
        return

    pdf_path = str(Path(pdf_path).resolve())
    if output_path:
        output_path = str(Path(output_path).resolve())

    # Get or create a session for this user
    session = _session_manager.get_or_create_session(user_session_id)
    set_current_session(session)

    # Reset session appropriately
    if is_continuation:
        session.soft_reset()
        if previous_edits:
            session.applied_edits = dict(previous_edits)
    else:
        session.reset()
        if original_pdf_bytes:
            session.original_pdf_bytes = original_pdf_bytes

    # Store context files and output path
    if context_files:
        session.context_files = context_files
    session.output_path = output_path
    session.is_continuation = is_continuation

    # Build context files section if available
    context_section = ""
    all_context_files = session.context_files or []
    if all_context_files:
        context_parts = []
        for cf in all_context_files:
            filename = cf.get("filename", "unknown") if isinstance(cf, dict) else getattr(cf, "filename", "unknown")
            content = cf.get("content", "") if isinstance(cf, dict) else getattr(cf, "content", "")
            if len(content) > 50000:
                content = content[:50000] + "\n\n[... content truncated ...]"
            context_parts.append(f"### {filename}\n{content}")
        context_section = f"""
## Reference Documents
The user has provided the following documents as context for filling out the form. Use information from these documents to fill the form fields accurately.

{chr(10).join(context_parts)}

---
"""

    # Build user prompt
    system_prompt = CONTINUATION_SYSTEM_PROMPT if is_continuation else SYSTEM_PROMPT
    
    if is_continuation:
        edits_summary = ""
        if previous_edits:
            edits_list = [f"  - {k}: {v}" for k, v in list(previous_edits.items())[:10]]
            if len(previous_edits) > 10:
                edits_list.append(f"  ... and {len(previous_edits) - 10} more fields")
            edits_summary = "\n".join(edits_list)

        user_prompt = f"""This is a CONTINUATION of a form-filling session.
{context_section}
PDF Path (already filled): {pdf_path}
Output Path: {output_path or pdf_path}

Previous fields that were filled:
{edits_summary if edits_summary else "(see current values in list_all_fields)"}

User's NEW request: {instructions}

IMPORTANT: The PDF already contains values from the previous turn.
Load it, check what's already filled, then ONLY change the specific fields the user is asking about.
Do NOT re-fill fields unless the user specifically asks to change them."""
    else:
        user_prompt = f"""Please fill out this PDF form:
{context_section}
PDF Path: {pdf_path}
Output Path: {output_path or pdf_path.replace('.pdf', '_filled.pdf')}

Instructions: {instructions}

Start by loading the PDF, then list the fields, fill them according to the instructions, and commit the edits."""

    yield {"type": "status", "message": "正在连接 DeepSeek API..."}

    try:
        client = get_deepseek_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        max_iterations = 30
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            yield {"type": "status", "message": f"智能代理第 {iteration} 轮处理..."}

            # Call LLM with function calling
            response = await client.chat.completions.create(
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                messages=messages,
                tools=FORM_FILLING_TOOLS,
                tool_choice="auto",
                temperature=0.0,
                stream=False,
            )

            message = response.choices[0].message
            messages.append(message)

            # Yield text content if present
            if message.content:
                yield {
                    "type": "text",
                    "text": message.content
                }

            # Check if we need to call functions
            if message.tool_calls:
                tool_results = []
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                    yield {
                        "type": "tool_use",
                        "tool_name": tool_name,
                        "tool_input": arguments,
                        "friendly": _get_friendly_tool_description(tool_name, arguments)
                    }

                    # Execute tool
                    result = await execute_tool(tool_name, arguments, session)

                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps(result)
                    })

                    # Yield tool result
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result
                    }

                    # Check if this was commit_edits and it succeeded
                    if tool_name == "commit_edits" and result.get("success"):
                        # Agent completed successfully
                        _session_manager.save_session(session)
                        yield {
                            "type": "complete",
                            "success": True,
                            "result": "表单填写完成",
                            "message_count": iteration,
                            "applied_count": len(session.applied_edits),
                            "applied_edits": dict(session.applied_edits),
                            "session_id": session.session_id,  # For multi-turn conversation tracking
                            "user_session_id": session.session_id,
                        }
                        return

                # Add tool results to messages for next iteration
                messages.extend(tool_results)
            else:
                # No tool calls, agent finished
                _session_manager.save_session(session)
                yield {
                    "type": "complete",
                    "success": True,
                    "result": message.content or "Agent completed",
                    "message_count": iteration,
                    "applied_count": len(session.applied_edits),
                    "applied_edits": dict(session.applied_edits),
                    "session_id": session.session_id,  # For multi-turn conversation tracking
                    "user_session_id": session.session_id,
                }
                return

        # Max iterations reached
        _session_manager.save_session(session)
        yield {
            "type": "complete",
            "success": False,
            "result": f"Agent reached maximum iterations ({max_iterations})",
            "message_count": iteration,
            "applied_count": len(session.applied_edits),
            "applied_edits": dict(session.applied_edits),
            "session_id": session.session_id,  # For multi-turn conversation tracking
            "user_session_id": session.session_id,
        }

    except Exception as e:
        print(f"[Agent Stream] Error: {e}")
        import traceback
        traceback.print_exc()
        yield {"type": "error", "error": f"Agent error: {str(e)}"}


async def run_agent(
    pdf_path: str,
    instructions: str,
    output_path: str | None = None,
    is_continuation: bool = False,
    previous_edits: dict[str, Any] | None = None,
    user_session_id: str | None = None,
) -> dict:
    """
    Run the form-filling agent using DeepSeek (non-streaming version).

    Args:
        pdf_path: Path to the PDF file to fill
        instructions: Natural language instructions for filling the form
        output_path: Optional path for the filled PDF
        is_continuation: Whether this is a continuation of a previous session
        previous_edits: Dict of field_id -> value from previous turns
        user_session_id: Unique ID for this user's form-filling session

    Returns:
        Summary of the agent execution
    """
    if not OPENAI_SDK_AVAILABLE:
        raise ValueError("OpenAI SDK not available. Install with: pip install openai")

    result = None
    async for message in run_agent_stream(
        pdf_path=pdf_path,
        instructions=instructions,
        output_path=output_path,
        is_continuation=is_continuation,
        previous_edits=previous_edits,
        user_session_id=user_session_id,
    ):
        if message.get("type") == "complete":
            result = message
            break
        elif message.get("type") == "error":
            raise ValueError(message.get("error", "Unknown error"))

    if not result:
        raise ValueError("Agent did not complete")

    return result


def _get_friendly_tool_description(tool_name: str, tool_input: dict) -> str:
    """Convert a tool call into a user-friendly description."""
    if tool_name == "load_pdf":
        return "正在加载 PDF 文档..."
    elif tool_name == "list_all_fields":
        return "正在扫描表单字段..."
    elif tool_name == "search_fields":
        query = tool_input.get("query", "")
        return f"正在搜索「{query}」相关字段..."
    elif tool_name == "get_field_details":
        return "正在查看字段详情..."
    elif tool_name == "set_field":
        field_id = tool_input.get("field_id", "")
        value = tool_input.get("value", "")
        value_preview = str(value)[:25] + "..." if len(str(value)) > 25 else str(value)
        return f"正在填写「{value_preview}」"
    elif tool_name == "get_pending_edits":
        return "正在检查待提交的修改..."
    elif tool_name == "commit_edits":
        return "正在保存表单..."
    return f"正在执行 {tool_name}..."


# Export compatibility flags
AGENT_SDK_AVAILABLE = OPENAI_SDK_AVAILABLE
AGENT_SDK_ERROR = None if OPENAI_SDK_AVAILABLE else "OpenAI SDK not available"
