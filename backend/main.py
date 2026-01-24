"""
FastAPI server for PDF form filling.

This is the main entry point. Run with:
    uvicorn main:app --reload

Endpoints:
    POST /analyze            - Upload PDF, get detected form fields
    POST /fill-agent         - Fill form fields (agent mode with tools) [RECOMMENDED]
    POST /fill-agent-stream  - Fill form fields with real-time streaming [RECOMMENDED]
    POST /fill               - Fill form fields (single-shot LLM mode) [LEGACY]
    GET  /                   - Serve the web UI

Note: The agent mode endpoints are recommended for production use. They provide
better accuracy, error recovery, and support for multi-turn conversations.
The single-shot /fill endpoint is maintained for backwards compatibility.
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    # Load .env file from project root (one level up from backend)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[Config] Loaded environment variables from {env_path}")
    else:
        # Also try loading from current directory
        load_dotenv()
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pdf_processor import detect_form_fields, edit_pdf_with_instructions, get_form_summary
from llm import map_instructions_to_fields
# Use DeepSeek-based agent
from agent_deepseek import run_agent, run_agent_stream, AGENT_SDK_AVAILABLE, AGENT_SDK_ERROR, _session_manager
from parser import (
    parse_files_stream, needs_parsing, is_simple_text,
    OPENPARSE_AVAILABLE, OPENPARSE_ERROR, ParsedFile
)
from asr import transcribe_audio, get_asr_status, GLM_ASR_AVAILABLE, GLM_ASR_ERROR


# ============================================================================
# App Setup
# ============================================================================

app = FastAPI(
    title="PDF Form Filler",
    description="Fill PDF forms using natural language instructions",
    version="0.1.0"
)


# Background task to cleanup old sessions periodically
import asyncio

async def periodic_session_cleanup():
    """Run session cleanup every hour."""
    while True:
        await asyncio.sleep(3600)  # 1 hour
        try:
            # Clean up sessions older than 24 hours
            _session_manager.cleanup_old_sessions(max_age_seconds=86400)
        except Exception as e:
            print(f"[Cleanup] Error during periodic cleanup: {e}")


@app.on_event("startup")
async def startup_event():
    """Start background tasks on app startup."""
    asyncio.create_task(periodic_session_cleanup())
    print("[App] Started periodic session cleanup task (every 1 hour, cleaning sessions older than 24 hours)")

# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API Models
# ============================================================================

class FieldInfo(BaseModel):
    field_id: str
    field_type: str
    page: int
    label_context: str
    friendly_label: Optional[str] = None
    current_value: Optional[str] = None
    options: Optional[list[str]] = None


class AnalyzeResponse(BaseModel):
    success: bool
    message: str
    fields: list[FieldInfo]
    field_count: int


class FillRequest(BaseModel):
    instructions: str
    use_llm: bool = True  # Set to False to use simple keyword mapping


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_pdf(file: UploadFile = File(...)):
    """
    Analyze a PDF to detect fillable form fields.
    
    Returns information about each detected field including:
    - field_id: Unique identifier for the field
    - field_type: text, checkbox, dropdown, or radio
    - label_context: Nearby text that describes the field
    - current_value: Any existing value in the field
    - options: Available options for dropdown/radio fields
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")
    
    pdf_bytes = await file.read()
    
    try:
        fields = detect_form_fields(pdf_bytes)
    except Exception as e:
        raise HTTPException(500, f"Failed to analyze PDF: {str(e)}")
    
    if not fields:
        return AnalyzeResponse(
            success=True,
            message="No fillable form fields found in this PDF. This endpoint only works with PDFs that have native AcroForm fields.",
            fields=[],
            field_count=0
        )
    
    field_infos = [
        FieldInfo(
            field_id=f.field_id,
            field_type=f.field_type.value,
            page=f.page,
            label_context=f.label_context,
            friendly_label=f.friendly_label,
            current_value=f.current_value,
            options=f.options
        )
        for f in fields
    ]
    
    return AnalyzeResponse(
        success=True,
        message=f"Found {len(fields)} fillable form fields",
        fields=field_infos,
        field_count=len(fields)
    )


@app.post("/fill", deprecated=True, include_in_schema=False)
async def fill_pdf(
    file: UploadFile = File(...),
    instructions: str = Form(...),
):
    """
    [LEGACY] Fill a PDF form using single-shot LLM mode.

    **DEPRECATED**: Use /fill-agent-stream for better accuracy and multi-turn support.

    This endpoint uses a single LLM call to map instructions to form fields.
    For complex forms or iterative refinement, use the agent endpoints instead.

    Args:
        file: The PDF file to fill
        instructions: Natural language description of what to fill
            e.g., "My name is John Doe, I live at 123 Main St,
                   my phone is 555-1234, and I agree to the terms"

    Returns:
        The filled PDF file as a download
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")
    
    pdf_bytes = await file.read()
    
    # Step 1: Detect form fields
    try:
        fields = detect_form_fields(pdf_bytes)
    except Exception as e:
        raise HTTPException(500, f"Failed to analyze PDF: {str(e)}")
    
    if not fields:
        raise HTTPException(
            400, 
            "No fillable form fields found in this PDF. "
            "This endpoint only works with PDFs that have native AcroForm fields."
        )
    
    # Step 2: Map instructions to fields using LLM
    # Note: The simple keyword mapping (use_llm=False) is no longer supported.
    # Use the agent endpoints for better accuracy.
    try:
        edits = map_instructions_to_fields(instructions, fields)
    except ValueError as e:
        raise HTTPException(
            500,
            f"LLM error: {str(e)}. Make sure DEEPSEEK_API_KEY is set."
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to process instructions: {str(e)}")
    
    if not edits:
        raise HTTPException(
            400,
            "Could not determine which fields to fill from your instructions. "
            "Try being more specific, e.g., 'Name: John Doe, Email: john@example.com'"
        )
    
    # Step 3: Apply edits
    try:
        filled_pdf = edit_pdf_with_instructions(pdf_bytes, edits)
    except Exception as e:
        raise HTTPException(500, f"Failed to fill PDF: {str(e)}")
    
    # Return the filled PDF
    filename = file.filename.replace('.pdf', '_filled.pdf')
    
    return Response(
        content=filled_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Fields-Filled": str(len(edits))
        }
    )


@app.post("/fill-preview", deprecated=True, include_in_schema=False)
async def fill_pdf_preview(
    file: UploadFile = File(...),
    instructions: str = Form(...),
):
    """
    [LEGACY] Preview what fields would be filled without actually filling them.

    **DEPRECATED**: Use /fill-agent-stream for better accuracy.

    Useful for debugging and understanding how instructions are mapped in single-shot mode.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")

    pdf_bytes = await file.read()

    # Detect fields
    try:
        fields = detect_form_fields(pdf_bytes)
    except Exception as e:
        raise HTTPException(500, f"Failed to analyze PDF: {str(e)}")

    if not fields:
        return {
            "success": False,
            "message": "No fillable form fields found",
            "fields": [],
            "edits": []
        }

    # Map instructions using LLM
    try:
        edits = map_instructions_to_fields(instructions, fields)
    except ValueError as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
    
    return {
        "success": True,
        "message": f"Would fill {len(edits)} of {len(fields)} fields",
        "fields": [f.to_dict() for f in fields],
        "edits": edits
    }


# ============================================================================
# Agent Mode Endpoint
# ============================================================================

@app.post("/fill-agent")
async def fill_pdf_agent(
    file: UploadFile = File(...),
    instructions: str = Form(...),
    max_iterations: int = Form(20),
):
    """
    Fill a PDF form using agent mode with tool calling (DeepSeek).
    
    This mode uses an iterative agent that can:
    - Search and inspect fields
    - Validate values before setting
    - Review pending edits before committing
    - Recover from errors
    
    Uses DeepSeek API with function calling.
    
    Args:
        file: The PDF file to fill
        instructions: Natural language description of what to fill
        max_iterations: Maximum agent iterations (default 20)
    
    Returns:
        The filled PDF file as a download, plus agent execution summary
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")
    
    pdf_bytes = await file.read()
    
    # Check for form fields first
    try:
        fields = detect_form_fields(pdf_bytes)
    except Exception as e:
        raise HTTPException(500, f"Failed to analyze PDF: {str(e)}")
    
    if not fields:
        raise HTTPException(
            400, 
            "No fillable form fields found in this PDF. "
            "This endpoint only works with PDFs that have native AcroForm fields."
        )
    
    # Run agent with DeepSeek
    try:
        import tempfile
        import os as os_module
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        
        output_path = tmp_path.replace('.pdf', '_filled.pdf')
        
        try:
            # Use await since we're in an async context
            summary = await run_agent(tmp_path, instructions, output_path)
            
            if os_module.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    filled_pdf = f.read()
            else:
                raise HTTPException(500, "Agent did not produce output PDF")
        finally:
            if os_module.path.exists(tmp_path):
                os_module.unlink(tmp_path)
            if os_module.path.exists(output_path):
                os_module.unlink(output_path)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(500, f"Agent error: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Agent failed: {str(e)}")
    
    # Handle different summary formats (SDK vs fallback)
    applied_count = summary.get("applied_count", 0)
    iterations = summary.get("iterations", summary.get("message_count", 0))
    
    if applied_count == 0:
        raise HTTPException(
            400,
            f"Agent could not fill any fields. Errors: {summary.get('errors', [])}"
        )
    
    # Return the filled PDF
    filename = file.filename.replace('.pdf', '_agent_filled.pdf')
    
    return Response(
        content=filled_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Fields-Filled": str(applied_count),
            "X-Agent-Iterations": str(iterations),
        }
    )


@app.post("/fill-agent-preview")
async def fill_pdf_agent_preview(
    file: UploadFile = File(...),
    instructions: str = Form(...),
    max_iterations: int = Form(20),
):
    """
    Run agent mode and return execution summary without downloading the PDF.
    
    Useful for debugging and understanding how the agent processes the form.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")
    
    pdf_bytes = await file.read()
    
    try:
        import tempfile
        import os as os_module
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        
        output_path = tmp_path.replace('.pdf', '_filled.pdf')
        
        try:
            # Use await since we're in an async context
            summary = await run_agent(tmp_path, instructions, output_path)
        finally:
            if os_module.path.exists(tmp_path):
                os_module.unlink(tmp_path)
            if os_module.path.exists(output_path):
                os_module.unlink(output_path)
                
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
    
    return {
        "success": True,
        "message": f"Agent completed with {summary.get('message_count', 0)} messages",
        "result": summary.get("result", ""),
    }


# ============================================================================
# Streaming Agent Endpoint (SSE)
# ============================================================================

from fastapi.responses import StreamingResponse
import json
import asyncio

@app.post("/fill-agent-stream")
async def fill_pdf_agent_stream(
    file: UploadFile = File(...),
    instructions: str = Form(...),
    max_iterations: int = Form(20),
    is_continuation: bool = Form(False),
    previous_edits: Optional[str] = Form(None),  # JSON string of field_id -> value
    resume_session_id: Optional[str] = Form(None),  # Session ID from previous turn
    user_session_id: Optional[str] = Form(None),  # Unique ID for this user's form-filling session
):
    """
    Fill a PDF form using agent mode with real-time streaming.

    Returns Server-Sent Events (SSE) stream with agent messages.

    Args:
        file: The PDF file to fill. For continuations, this should be the already-filled PDF.
        instructions: Natural language instructions for this turn
        is_continuation: Set to true for multi-turn conversations (subsequent messages)
        previous_edits: JSON string of {field_id: value} from previous turns
        resume_session_id: Session ID from previous turn to resume conversation context
        user_session_id: Unique ID for this user's form-filling session (for concurrent users)

    Event types:
    - init: Session initialized with field count
    - iteration: New iteration started
    - text: Agent thinking/response text
    - tool_start: Tool call started
    - tool_end: Tool call completed with result
    - complete: Agent finished (includes applied_edits, session_id, and user_session_id for tracking)
    - pdf_ready: Final summary with filled PDF (hex-encoded)
    - error: Error occurred
    """
    if not file.filename.lower().endswith('.pdf'):
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'error': 'File must be a PDF'})}\n\n"
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream"
        )
    
    # Check SDK availability early
    if not AGENT_SDK_AVAILABLE:
        async def sdk_error_stream():
            yield f"data: {json.dumps({'type': 'error', 'error': f'DeepSeek agent not available: {AGENT_SDK_ERROR}. Install with: pip install openai'})}\n\n"
        return StreamingResponse(
            sdk_error_stream(),
            media_type="text/event-stream"
        )
    
    pdf_bytes = await file.read()
    
    # Parse previous_edits JSON if provided
    parsed_previous_edits = None
    if previous_edits:
        try:
            parsed_previous_edits = json.loads(previous_edits)
        except json.JSONDecodeError:
            parsed_previous_edits = None

    async def event_stream():
        import tempfile
        import os as os_module

        tmp_path = None
        output_path = None

        # Send immediate acknowledgment
        cont_msg = "（继续对话）" if is_continuation else ""
        yield f"data: {json.dumps({'type': 'init', 'message': f'已连接，正在初始化智能代理{cont_msg}...'})}\n\n"

        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            output_path = tmp_path.replace('.pdf', '_filled.pdf')

            yield f"data: {json.dumps({'type': 'status', 'message': f'PDF 已保存，正在启动智能代理...'})}\n\n"

            # Stream messages from DeepSeek agent with continuation params
            # Pass original PDF bytes only for new sessions (not continuations)
            message_count = 0
            async for message in run_agent_stream(
                tmp_path,
                instructions,
                output_path,
                is_continuation=is_continuation,
                previous_edits=parsed_previous_edits,
                resume_session_id=resume_session_id,
                user_session_id=user_session_id,
                original_pdf_bytes=pdf_bytes if not is_continuation else None,
            ):
                message_count += 1
                # Convert message to JSON and send as SSE
                yield f"data: {json.dumps(message, default=str)}\n\n"
            
            if message_count == 0:
                yield f"data: {json.dumps({'type': 'error', 'error': '智能代理未产生任何消息'})}\n\n"
            
            # After streaming completes, check for output PDF
            if output_path and os_module.path.exists(output_path):
                # Read the filled PDF and include in final message
                with open(output_path, 'rb') as f:
                    pdf_hex = f.read().hex()
                yield f"data: {json.dumps({'type': 'pdf_ready', 'pdf_bytes': pdf_hex})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'error': '未生成输出 PDF'})}\n\n"
                
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            # Clean up temp files (ignore Windows lock errors)
            try:
                if tmp_path and os_module.path.exists(tmp_path):
                    os_module.unlink(tmp_path)
            except PermissionError:
                # File still locked by PyMuPDF on Windows - will be cleaned up later
                pass
            try:
                if output_path and os_module.path.exists(output_path):
                    os_module.unlink(output_path)
            except PermissionError:
                pass
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ============================================================================
# Static Files (Web UI)
# ============================================================================

# Serve the frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

@app.get("/")
async def serve_index():
    """Serve the main web UI."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "PDF Form Filler API. See /docs for API documentation."}


# Mount static files if frontend directory exists
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ============================================================================
# Context File Parsing
# ============================================================================

@app.post("/parse-files")
async def parse_context_files(
    files: list[UploadFile] = File(...),
    parse_mode: str = Form("cost_effective"),
    user_session_id: Optional[str] = Form(None),
    api_key: str = Form(...),
):
    """
    Parse uploaded context files using OpenParse (for complex files) or direct read (for simple text).

    Streams progress updates via SSE.

    Args:
        files: Up to 5 files to parse
        parse_mode: "fast" or "detailed"
        user_session_id: Optional session ID to associate parsed files with
        api_key: Not used for OpenParse (open-source, no API key needed)

    Returns:
        SSE stream with progress updates and final results
    """
    # OpenParse is open-source and doesn't require an API key
    # API key parameter is kept for backwards compatibility but not validated

    # Validate file count
    if len(files) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 files allowed")

    if len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # Validate parse mode
    if parse_mode not in ("fast", "detailed"):
        raise HTTPException(status_code=400, detail="Invalid parse_mode. Use 'fast' or 'detailed'")

    # Check if OpenParse is available for files that need it
    files_needing_parse = [f for f in files if needs_parsing(f.filename or "")]
    if files_needing_parse and not OPENPARSE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=f"OpenParse not available: {OPENPARSE_ERROR}. Cannot parse: {[f.filename for f in files_needing_parse]}"
        )

    # Read all file bytes
    file_data = []
    for f in files:
        content = await f.read()
        file_data.append((content, f.filename or "unknown"))

    async def event_stream():
        yield f"data: {json.dumps({'type': 'init', 'message': f'正在解析 {len(file_data)} 个文件...'})}\n\n"

        try:
            # OpenParse doesn't require API key, but we pass it for backwards compatibility
            async for event in parse_files_stream(file_data, parse_mode, api_key=None):
                yield f"data: {json.dumps(event)}\n\n"

                # If this is the complete event, also store in session if session_id provided
                if event.get("type") == "complete" and user_session_id:
                    # Use get_or_create to ensure session exists for storing context files
                    session = _session_manager.get_or_create_session(user_session_id)
                    if session:
                        # Store parsed files in session
                        parsed_files = []
                        for result in event.get("results", []):
                            if result.get("content"):
                                parsed_files.append(ParsedFile(
                                    filename=result["filename"],
                                    content=result["content"],
                                    was_parsed=result.get("parsed", False)
                                ))
                        session.context_files = parsed_files
                        # Save session to persist the context files
                        _session_manager._save_session_to_db(session)
                        print(f"[Parse] Stored {len(parsed_files)} context files in session {user_session_id}")

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/parse-status")
async def get_parse_status():
    """Check if OpenParse is available."""
    return {
        "openparse_available": OPENPARSE_AVAILABLE,
        "openparse_error": OPENPARSE_ERROR if not OPENPARSE_AVAILABLE else None,
    }


@app.post("/validate-api-key")
async def validate_api_key(api_key: str = Form(...)):
    """
    Validate a DeepSeek API key by making a test request.

    This endpoint is used to gate access to the application.
    Users must provide a valid DeepSeek API key before using the app.
    Note: OpenParse doesn't require an API key (open-source), but DeepSeek LLM does.
    """
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=400, detail="API key is required")

    api_key = api_key.strip()

    # Test the key by making a request to DeepSeek API
    try:
        from openai import OpenAI
        import httpx
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        # Create client without proxy to avoid conflicts with system proxy settings
        http_client = httpx.Client(proxy=None)
        client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

        # Make a simple test request to validate the key
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )

        return {"valid": True, "message": "DeepSeek API key is valid"}

    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            raise HTTPException(
                status_code=401,
                detail="Invalid API key. Please check your DeepSeek API key."
            )
        elif "403" in error_msg or "forbidden" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail="API key does not have permission. Please check your DeepSeek account."
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to validate API key: {error_msg}"
            )


# ============================================================================
# ASR (Speech-to-Text) Endpoint
# ============================================================================

@app.post("/asr")
async def speech_to_text(audio: UploadFile = File(...)):
    """
    Convert speech audio to text using GLM-ASR.
    
    Accepts audio files (webm, wav, mp3, etc.) and returns transcribed text.
    Requires GLM-ASR model to be available (transformers>=5.0.0 from source).
    
    Repository: https://github.com/zai-org/GLM-ASR
    """
    if not GLM_ASR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=f"ASR 服务不可用: {GLM_ASR_ERROR}. 请参考 https://github.com/zai-org/GLM-ASR 安装依赖。"
        )
    
    import tempfile
    
    # Save uploaded audio to temp file
    suffix = Path(audio.filename).suffix if audio.filename else '.webm'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        text = await transcribe_audio(tmp_path)
        return {"text": text, "success": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"语音识别失败: {str(e)}"
        )
    finally:
        # Clean up temp file
        import os
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.get("/asr/status")
async def asr_status():
    """Get ASR module status and availability."""
    return get_asr_status()


# ============================================================================
# Session PDF Retrieval
# ============================================================================

@app.get("/session/{session_id}/pdf")
async def get_session_pdf(session_id: str):
    """
    Retrieve the filled PDF for a session.

    This allows the frontend to restore the PDF when a user returns to a session.
    Returns the PDF bytes as a file response.
    """
    pdf_bytes = _session_manager.get_session_pdf_bytes(session_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Session not found or no PDF available")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=session_{session_id}.pdf"
        }
    )


@app.get("/session/{session_id}/original-pdf")
async def get_session_original_pdf(session_id: str):
    """
    Retrieve the original (unfilled) PDF for a session.

    This allows the frontend to show both original and filled views when restoring a session.
    Returns the PDF bytes as a file response.
    """
    pdf_bytes = _session_manager.get_session_original_pdf_bytes(session_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Session not found or no original PDF available")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=session_{session_id}_original.pdf"
        }
    )


@app.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """
    Get session metadata (without PDF bytes).

    Returns applied edits and whether PDFs are available.
    """
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get context files info (without full content)
    context_files_info = []
    if session.context_files:
        for cf in session.context_files:
            if isinstance(cf, dict):
                context_files_info.append({
                    "filename": cf.get("filename", "unknown"),
                    "was_parsed": cf.get("was_parsed", False),
                    "content_length": len(cf.get("content", ""))
                })
            else:
                context_files_info.append({
                    "filename": getattr(cf, "filename", "unknown"),
                    "was_parsed": getattr(cf, "was_parsed", False),
                    "content_length": len(getattr(cf, "content", ""))
                })

    return {
        "session_id": session.session_id,
        "has_pdf": session.current_pdf_bytes is not None,
        "has_original_pdf": session.original_pdf_bytes is not None,
        "applied_edits": session.applied_edits,
        "field_count": len(session.applied_edits) if session.applied_edits else 0,
        "context_files": context_files_info,
        "context_files_count": len(context_files_info),
    }


@app.get("/session/{session_id}/context-files")
async def get_session_context_files(session_id: str):
    """
    Get the full context files for a session.

    Returns the list of context files with their full content.
    """
    context_files = _session_manager.get_session_context_files(session_id)
    if context_files is None:
        raise HTTPException(status_code=404, detail="Session not found or no context files")

    return {
        "session_id": session_id,
        "context_files": context_files,
    }


# ============================================================================
# Run directly for development
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("\n" + "="*60)
    print("PDF Form Filler Server")
    print("="*60)
    print("\nRecommended Endpoints:")
    print("  POST /analyze            - Detect form fields in a PDF")
    print("  POST /fill-agent-stream  - Fill form (agent mode, SSE streaming)")
    print("  POST /fill-agent         - Fill form (agent mode)")
    print("\nLegacy Endpoints (deprecated):")
    print("  POST /fill               - Fill (single-shot LLM mode)")
    print("  POST /fill-preview       - Preview single-shot mode")
    print("\nOther:")
    print("  GET  /docs               - API documentation (Swagger UI)")
    print("\nWeb UI: http://localhost:8000")
    print("Next.js UI: http://localhost:3000 (run 'npm run dev' in web/)")
    print("\nTip: For auto-reload during development, run:")
    print("  uvicorn main:app --reload")
    print("="*60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)

