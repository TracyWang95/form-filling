"""
File parsing module using OpenParse.

Provides functionality to parse various file types (PDF, PPTX, DOCX, images)
into markdown format for use as context in the form-filling agent.
"""

import os
from pathlib import Path
from typing import AsyncGenerator, Literal

# File extensions that don't need parsing (already text-based)
SIMPLE_TEXT_EXTENSIONS = {
    '.txt', '.md', '.markdown', '.csv', '.json', '.xml', '.html', '.htm',
    '.py', '.js', '.ts', '.jsx', '.tsx', '.css', '.scss', '.yaml', '.yml',
    '.toml', '.ini', '.cfg', '.conf', '.sh', '.bash', '.zsh', '.sql',
    '.r', '.rb', '.go', '.java', '.c', '.cpp', '.h', '.hpp', '.rs',
}

# File extensions that need OpenParse
PARSEABLE_EXTENSIONS = {
    '.pdf', '.pptx', '.ppt', '.docx', '.doc', '.xlsx', '.xls',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp',
}

# Parse mode options (OpenParse uses different modes)
ParseMode = Literal["fast", "detailed"]

# Try to import OpenParse
OPENPARSE_AVAILABLE = False
OPENPARSE_ERROR = None

try:
    import openparse
    OPENPARSE_AVAILABLE = True
except ImportError as e:
    OPENPARSE_ERROR = str(e)
    print(f"[Parser] OpenParse not available: {e}")
    print("[Parser] Install with: pip install openparse")


def needs_parsing(filename: str) -> bool:
    """Check if a file needs to be parsed with OpenParse."""
    ext = Path(filename).suffix.lower()
    return ext in PARSEABLE_EXTENSIONS


def is_simple_text(filename: str) -> bool:
    """Check if a file is simple text that can be read directly."""
    ext = Path(filename).suffix.lower()
    return ext in SIMPLE_TEXT_EXTENSIONS


def get_parser(mode: ParseMode = "fast", api_key: str | None = None):
    """
    Get an OpenParse parser instance with the specified mode.

    Args:
        mode: "fast" or "detailed" (OpenParse modes)
        api_key: Not used for OpenParse (open-source, no API key needed)

    Returns:
        OpenParse parser instance configured for the mode
    """
    if not OPENPARSE_AVAILABLE:
        raise RuntimeError(f"OpenParse not available: {OPENPARSE_ERROR}")

    # OpenParse configuration based on mode
    if mode == "detailed":
        # Detailed mode: higher quality parsing
        return openparse.DocumentParser(
            table_args={"min_table_confidence": 0.8},
            do_ocr=True,
            ocr_args={"ocr_strategy": "high_res"},
        )
    else:
        # Fast mode: faster parsing with lower resource usage
        return openparse.DocumentParser(
            table_args={"min_table_confidence": 0.6},
            do_ocr=False,  # Skip OCR for speed
        )


async def parse_file(
    file_bytes: bytes,
    filename: str,
    mode: ParseMode = "fast",
    api_key: str | None = None,
) -> str:
    """
    Parse a file and return its markdown content.

    Args:
        file_bytes: The file content as bytes
        filename: The original filename (needed for OpenParse)
        mode: The parsing mode to use ("fast" or "detailed")
        api_key: Not used for OpenParse (open-source, no API key needed)

    Returns:
        Markdown string of the parsed content
    """
    import tempfile
    import asyncio

    ext = Path(filename).suffix.lower()

    # If it's a simple text file, just decode and return
    if is_simple_text(filename):
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return file_bytes.decode('latin-1')

    # If it doesn't need parsing and isn't simple text, return error
    if not needs_parsing(filename):
        return f"[Unsupported file type: {ext}]"

    # Use OpenParse
    if not OPENPARSE_AVAILABLE:
        raise RuntimeError(f"OpenParse not available: {OPENPARSE_ERROR}")

    parser = get_parser(mode, api_key=api_key)

    # Write bytes to temp file (OpenParse API takes file paths)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        # Parse the file synchronously (OpenParse doesn't have async method)
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, parser.parse, tmp_path)

        # Get markdown from the result
        # OpenParse returns a parsed document with markdown content
        if hasattr(result, 'markdown'):
            return result.markdown
        elif hasattr(result, 'text'):
            return result.text
        elif isinstance(result, str):
            return result
        elif hasattr(result, 'pages'):
            # If result has pages, extract markdown from each page
            markdown_parts = []
            for page in result.pages:
                if hasattr(page, 'markdown') and page.markdown:
                    markdown_parts.append(page.markdown)
                elif hasattr(page, 'text') and page.text:
                    markdown_parts.append(page.text)
            return "\n\n".join(markdown_parts) if markdown_parts else "[No content extracted]"
        else:
            return str(result) if result else "[No content extracted]"
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


async def parse_files_stream(
    files: list[tuple[bytes, str]],
    mode: ParseMode = "fast",
    api_key: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Parse multiple files with streaming status updates.

    Args:
        files: List of (file_bytes, filename) tuples
        mode: The parsing mode to use ("fast" or "detailed")
        api_key: Not used for OpenParse (open-source, no API key needed)

    Yields:
        Status updates and results as dicts
    """
    total = len(files)
    results = []

    yield {"type": "start", "total": total, "mode": mode}

    for i, (file_bytes, filename) in enumerate(files):
        yield {
            "type": "progress",
            "current": i + 1,
            "total": total,
            "filename": filename,
            "status": "parsing"
        }

        try:
            # Check if file needs parsing
            if is_simple_text(filename):
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "filename": filename,
                    "status": "reading_text"
                }
                try:
                    content = file_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    content = file_bytes.decode('latin-1')

                results.append({
                    "filename": filename,
                    "content": content,
                    "parsed": False,
                    "error": None
                })

            elif needs_parsing(filename):
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "filename": filename,
                    "status": "openparse"
                }

                content = await parse_file(file_bytes, filename, mode, api_key=api_key)
                results.append({
                    "filename": filename,
                    "content": content,
                    "parsed": True,
                    "error": None
                })

            else:
                ext = Path(filename).suffix.lower()
                results.append({
                    "filename": filename,
                    "content": None,
                    "parsed": False,
                    "error": f"Unsupported file type: {ext}"
                })

            yield {
                "type": "progress",
                "current": i + 1,
                "total": total,
                "filename": filename,
                "status": "complete"
            }

        except Exception as e:
            results.append({
                "filename": filename,
                "content": None,
                "parsed": False,
                "error": str(e)
            })
            yield {
                "type": "progress",
                "current": i + 1,
                "total": total,
                "filename": filename,
                "status": "error",
                "error": str(e)
            }

    yield {
        "type": "complete",
        "results": results,
        "success_count": sum(1 for r in results if r["error"] is None),
        "error_count": sum(1 for r in results if r["error"] is not None)
    }


class ParsedFile:
    """Represents a parsed file with its content."""

    def __init__(
        self,
        filename: str,
        content: str,
        original_bytes: bytes | None = None,
        was_parsed: bool = False
    ):
        self.filename = filename
        self.content = content
        self.original_bytes = original_bytes
        self.was_parsed = was_parsed

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "content": self.content,
            "was_parsed": self.was_parsed,
            # Don't include original_bytes in dict - it's for internal use
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedFile":
        return cls(
            filename=data["filename"],
            content=data["content"],
            was_parsed=data.get("was_parsed", False)
        )
