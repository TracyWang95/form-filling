"""
LLM integration for mapping natural language instructions to form fields.

Uses DeepSeek API (OpenAI-compatible).

This module handles the "AI" part - understanding what the user wants
and mapping it to specific form fields.

Edit this file to:
- Change the model (deepseek-chat, deepseek-coder, etc.)
- Customize the prompts
- Add validation/retry logic
"""

import os
from typing import Union
import json
from pathlib import Path

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

from openai import OpenAI
from pydantic import BaseModel, Field

from pdf_processor import DetectedField


# ============================================================================
# Structured Output Models (Pydantic)
# ============================================================================

class FieldEdit(BaseModel):
    """A single field edit to apply to the PDF form."""
    field_id: str = Field(description="The exact field_id from the available fields")
    value: Union[str, bool] = Field(description="The value to fill in. String for text fields, boolean for checkboxes.")


class FormEdits(BaseModel):
    """Collection of field edits to apply to the form."""
    edits: list[FieldEdit] = Field(
        default_factory=list,
        description="List of field edits. Only include fields that should be filled based on the instructions."
    )


# ============================================================================
# Configuration
# ============================================================================

def get_client() -> OpenAI:
    """
    Get the DeepSeek client (OpenAI-compatible).
    
    Set DEEPSEEK_API_KEY environment variable.
    Optionally set DEEPSEEK_BASE_URL (default: https://api.deepseek.com)
    """
    import httpx
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    
    if not api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY environment variable is required. "
            "Set it with: export DEEPSEEK_API_KEY=your-key-here"
        )
    
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    
    # Create client without proxy to avoid conflicts with system proxy settings
    http_client = httpx.Client(proxy=None)
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client
    )


# Default model - DeepSeek models
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


# ============================================================================
# Core LLM Function
# ============================================================================

def map_instructions_to_fields(
    instructions: str,
    fields: list[DetectedField],
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """
    Use LLM to map natural language instructions to specific form field edits.
    
    Uses DeepSeek API with JSON mode for structured outputs.
    
    Args:
        instructions: Natural language description of what to fill
            e.g., "My name is John Doe, I live at 123 Main St, and I agree to the terms"
        fields: List of detected form fields from the PDF
        model: DeepSeek model to use
        
    Returns:
        List of edits: [{"field_id": str, "value": str|bool}, ...]
    """
    if not fields:
        return []
    
    # Build field descriptions for the LLM
    field_descriptions = _build_field_descriptions(fields)
    
    prompt = f"""You are a form-filling assistant. Given a list of form fields from a PDF and user instructions, determine which fields should be filled with what values.

## Available Form Fields:
{field_descriptions}

## User Instructions:
{instructions}

## Your Task:
Analyze the user's instructions and determine which fields should be filled.

Rules:
- Only include fields that should be filled based on the instructions
- If a field doesn't match any instruction, don't include it
- For checkboxes: use true if the user indicates agreement/yes/checking, false otherwise
- For dropdowns: use one of the available options that best matches the user's intent
- Match field_id exactly as shown above

Return a JSON object with the following structure:
{{
  "edits": [
    {{"field_id": "field_id_here", "value": "value_here"}},
    ...
  ]
}}

For checkbox fields, use boolean true/false. For text fields, use strings."""

    client = get_client()
    
    # Use DeepSeek API with JSON mode for structured output
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that returns valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0,  # Deterministic for form filling
        max_tokens=4096,
    )
    
    # Parse the JSON response
    response_text = response.choices[0].message.content.strip()
    
    # Extract JSON from response (handle cases where it might be wrapped in code blocks)
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()
    
    try:
        result_dict = json.loads(response_text)
        # Convert to FormEdits for validation
        result = FormEdits(**result_dict)
    except (json.JSONDecodeError, ValueError) as e:
        # Fallback: try to extract edits directly
        print(f"Warning: Failed to parse JSON response: {e}")
        print(f"Response was: {response_text[:200]}")
        return []
    
    # Validate field_ids exist
    valid_field_ids = {f.field_id for f in fields}
    edits = [
        {"field_id": edit.field_id, "value": edit.value}
        for edit in result.edits
        if edit.field_id in valid_field_ids
    ]
    
    return edits


def _build_field_descriptions(fields: list[DetectedField]) -> str:
    """Build a human-readable description of fields for the LLM."""
    lines = []
    
    for f in fields:
        field_type_str = f.field_type.value if hasattr(f.field_type, 'value') else str(f.field_type)
        desc = f"- **{f.field_id}** (type: {field_type_str})"
        
        if f.label_context:
            # Truncate long context
            context = f.label_context[:150]
            if len(f.label_context) > 150:
                context += "..."
            desc += f"\n  Context/Label: \"{context}\""
        
        if f.options:
            desc += f"\n  Options: {f.options}"
            
        if f.current_value:
            desc += f"\n  Current value: \"{f.current_value}\""
            
        lines.append(desc)
    
    return "\n".join(lines)


# ============================================================================
# Alternative: Simple Rule-Based Mapping (No LLM)
# ============================================================================

def simple_keyword_mapping(
    instructions: str,
    fields: list[DetectedField],
) -> list[dict]:
    """
    A simple keyword-based mapping without LLM.
    
    This is useful for testing or when you don't want to use an LLM.
    Override or extend this for custom logic.
    
    Example:
        instructions = "name: John Doe, email: john@example.com"
        -> Looks for fields with "name" in context, fills with "John Doe"
    """
    edits = []
    
    # Parse simple key: value pairs
    # Supports "key: value" and "key = value" formats
    import re
    pairs = re.findall(r'(\w+(?:\s+\w+)?)\s*[:=]\s*([^,;\n]+)', instructions)
    
    for key, value in pairs:
        key = key.strip().lower()
        value = value.strip()
        
        # Find fields that match this key
        for field in fields:
            context_lower = field.label_context.lower()
            field_name_lower = (field.native_field_name or "").lower()
            
            if key in context_lower or key in field_name_lower:
                edits.append({
                    "field_id": field.field_id,
                    "value": value
                })
                break  # Only fill first matching field
    
    return edits


# ============================================================================
# Testing
# ============================================================================

if __name__ == "__main__":
    import json
    from pdf_processor import FieldType
    
    print("Testing LLM integration with DeepSeek API...")
    print(f"Model: {DEFAULT_MODEL}")
    
    # Create some dummy fields for testing
    test_fields = [
        DetectedField(
            field_id="page0_full_name",
            field_type=FieldType.TEXT,
            bbox=(100, 100, 300, 120),
            page=0,
            label_context="Full Name: | Enter your legal name",
            native_field_name="full_name"
        ),
        DetectedField(
            field_id="page0_email",
            field_type=FieldType.TEXT, 
            bbox=(100, 140, 300, 160),
            page=0,
            label_context="Email Address:",
            native_field_name="email"
        ),
        DetectedField(
            field_id="page0_agree",
            field_type=FieldType.CHECKBOX,
            bbox=(100, 200, 120, 220),
            page=0,
            label_context="I agree to the terms and conditions",
            native_field_name="agree_terms"
        ),
    ]
    
    # Test instructions
    test_instructions = "My name is Jerry Liu, my email is jerry@llamaindex.ai, and I agree to the terms."
    
    print(f"\nTest instructions: {test_instructions}")
    print("\n" + "="*50)
    print("Simple keyword mapping result:")
    print("="*50)
    simple_result = simple_keyword_mapping(test_instructions, test_fields)
    print(json.dumps(simple_result, indent=2))
    
    print("\n" + "="*50)
    print("LLM mapping result (requires DEEPSEEK_API_KEY):")
    print("="*50)
    try:
        llm_result = map_instructions_to_fields(test_instructions, test_fields)
        print(json.dumps(llm_result, indent=2))
    except ValueError as e:
        print(f"Skipped: {e}")
    except Exception as e:
        print(f"Error: {e}")
