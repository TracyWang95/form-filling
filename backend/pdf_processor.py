"""
Core PDF form processing logic.

This module handles:
1. Detecting fillable AcroForm fields in PDFs
2. Applying edits to form fields

Edit this file to customize PDF processing behavior.
"""

from dataclasses import dataclass, asdict
from enum import Enum
import fitz  # PyMuPDF
import json
import os
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


class FieldType(Enum):
    TEXT = "text"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    RADIO = "radio"


@dataclass
class DetectedField:
    """Represents a detected form field in the PDF."""
    field_id: str
    field_type: FieldType
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page: int
    label_context: str  # nearby text for semantic understanding
    current_value: str | None = None  # current value if any
    options: list[str] | None = None  # for dropdowns/radios
    native_field_name: str | None = None  # the AcroForm field name
    friendly_label: str | None = None  # LLM-generated clean label for display

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d['field_type'] = self.field_type.value
        return d


@dataclass 
class FieldEdit:
    """Represents an edit to apply to a form field."""
    field_id: str
    value: str | bool


def detect_form_fields(pdf_bytes: bytes, generate_friendly_labels: bool = True) -> list[DetectedField]:
    """
    Detect all fillable AcroForm fields in the PDF.

    This ONLY detects native PDF form widgets (AcroForm fields).
    Non-form PDFs will return an empty list.

    Args:
        pdf_bytes: The PDF file as bytes
        generate_friendly_labels: If True, use LLM to generate clean labels

    Returns:
        List of detected form fields with their metadata
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    fields = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        widgets = list(page.widgets())

        for widget in widgets:
            # Skip null/invalid widgets
            if not widget.field_name:
                continue

            field_type = _widget_type_to_field_type(widget.field_type)

            # Get dropdown/radio options if applicable
            options = None
            if widget.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                options = widget.choice_values or []

            # Get current value
            current_value = widget.field_value
            if isinstance(current_value, bool):
                current_value = str(current_value).lower()

            fields.append(DetectedField(
                field_id=f"page{page_num}_{widget.field_name}",
                field_type=field_type,
                bbox=tuple(widget.rect),
                page=page_num,
                label_context=_extract_nearby_text(page, widget.rect),
                current_value=current_value,
                options=options,
                native_field_name=widget.field_name
            ))

    doc.close()

    # Generate friendly labels using LLM
    if generate_friendly_labels and fields:
        fields = _generate_friendly_labels(fields)

    # print(f"Detected {len(fields)} fields")
    # print(fields)
    # raise Exception("Stop here")

    return fields


def apply_edits(pdf_bytes: bytes, edits: list[FieldEdit]) -> bytes:
    """
    Apply a list of edits to form fields in the PDF.
    
    Args:
        pdf_bytes: The original PDF as bytes
        edits: List of field edits to apply
        
    Returns:
        Modified PDF as bytes
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Build a lookup of field_id -> edit
    edit_map = {e.field_id: e for e in edits}
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        for widget in page.widgets():
            if not widget.field_name:
                continue
                
            field_id = f"page{page_num}_{widget.field_name}"
            
            if field_id in edit_map:
                edit = edit_map[field_id]
                _apply_widget_edit(widget, edit.value)
    
    result = doc.tobytes()
    doc.close()
    return result


def edit_pdf_with_instructions(
    pdf_bytes: bytes,
    edits: list[dict],  # List of {"field_id": str, "value": str|bool}
) -> bytes:
    """
    Edit a PDF using a pre-computed list of field edits.
    
    This is the main entry point after LLM has mapped instructions to fields.
    
    Args:
        pdf_bytes: The PDF file as bytes
        edits: List of edits with field_id and value
        
    Returns:
        Modified PDF as bytes
    """
    field_edits = [
        FieldEdit(
            field_id=e["field_id"],
            value=e["value"]
        )
        for e in edits
    ]
    return apply_edits(pdf_bytes, field_edits)


# ============================================================================
# Helper Functions
# ============================================================================

def _extract_nearby_text(page: fitz.Page, rect: fitz.Rect, radius: int = 100) -> str:
    """
    Extract text near a bounding box to understand field context.

    This uses a DIRECTIONAL approach for complex form layouts:
    - Prioritize text to the LEFT (where labels usually are)
    - Include text ABOVE (for vertically stacked labels)
    - Be conservative with RIGHT side (avoid picking up adjacent columns)

    Returns nearby text organized by direction for better LLM understanding.
    """
    page_rect = page.rect
    field_x = rect.x0
    field_y = rect.y0
    field_width = rect.width
    field_height = rect.height
    
    text_parts = []
    
    # 1. Text to the LEFT of field (most important - labels usually here)
    left_rect = fitz.Rect(
        max(0, field_x - 250),  # Look up to 250px left
        field_y - 10,           # Roughly same vertical position
        field_x - 5,
        field_y + field_height + 10
    )
    left_rect.intersect(page_rect)
    left_text = page.get_text("text", clip=left_rect).strip()
    if left_text:
        # Clean and take the rightmost text (closest to field)
        left_lines = [l.strip() for l in left_text.split('\n') if l.strip()]
        if left_lines:
            text_parts.append(f"LEFT: {' | '.join(left_lines[-3:])}")  # Last 3 lines (closest)
    
    # 2. Text ABOVE the field (for vertically stacked labels)
    above_rect = fitz.Rect(
        field_x - 50,
        max(0, field_y - 80),   # Look up to 80px above
        field_x + field_width + 50,
        field_y - 2
    )
    above_rect.intersect(page_rect)
    above_text = page.get_text("text", clip=above_rect).strip()
    if above_text:
        above_lines = [l.strip() for l in above_text.split('\n') if l.strip()]
        if above_lines:
            text_parts.append(f"ABOVE: {' | '.join(above_lines[-2:])}")  # Bottom 2 lines (closest)
    
    # 3. Text to the RIGHT (limited - avoid adjacent columns)
    right_rect = fitz.Rect(
        rect.x1 + 5,
        field_y - 5,
        min(page_rect.x1, rect.x1 + 100),  # Only 100px right (conservative)
        field_y + field_height + 5
    )
    right_rect.intersect(page_rect)
    right_text = page.get_text("text", clip=right_rect).strip()
    if right_text:
        right_lines = [l.strip() for l in right_text.split('\n') if l.strip()]
        if right_lines:
            text_parts.append(f"RIGHT: {' | '.join(right_lines[:2])}")  # First 2 lines only
    
    # 4. Text BELOW (for fields with labels underneath)
    below_rect = fitz.Rect(
        field_x - 30,
        rect.y1 + 2,
        field_x + field_width + 30,
        min(page_rect.y1, rect.y1 + 40)  # Only 40px below
    )
    below_rect.intersect(page_rect)
    below_text = page.get_text("text", clip=below_rect).strip()
    if below_text:
        below_lines = [l.strip() for l in below_text.split('\n') if l.strip()]
        if below_lines:
            text_parts.append(f"BELOW: {' | '.join(below_lines[:1])}")  # First line only
    
    result = ' || '.join(text_parts) if text_parts else ""
    
    # Fallback: if directional search found nothing, use original approach
    if not result:
        search_rect = fitz.Rect(rect)
        search_rect.x0 -= radius
        search_rect.y0 -= radius
        search_rect.x1 += radius
        search_rect.y1 += radius
        search_rect.intersect(page_rect)
        text = page.get_text("text", clip=search_rect).strip()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        result = ' | '.join(lines)
    
    return result


def _widget_type_to_field_type(widget_type: int) -> FieldType:
    """Map PyMuPDF widget types to our FieldType enum."""
    mapping = {
        fitz.PDF_WIDGET_TYPE_TEXT: FieldType.TEXT,
        fitz.PDF_WIDGET_TYPE_CHECKBOX: FieldType.CHECKBOX,
        fitz.PDF_WIDGET_TYPE_COMBOBOX: FieldType.DROPDOWN,
        fitz.PDF_WIDGET_TYPE_LISTBOX: FieldType.DROPDOWN,
        fitz.PDF_WIDGET_TYPE_RADIOBUTTON: FieldType.RADIO,
    }
    return mapping.get(widget_type, FieldType.TEXT)


def _apply_widget_edit(widget: fitz.Widget, value: str | bool):
    """Apply an edit to a specific widget."""
    widget_type = widget.field_type

    if widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
        # For checkboxes, convert string "true"/"false" to bool
        if isinstance(value, str):
            value = value.lower() in ('true', 'yes', '1', 'checked')
        widget.field_value = value

    elif widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
        # Radio buttons need special handling
        widget.field_value = str(value)

    else:
        # Text fields, dropdowns, etc.
        widget.field_value = str(value)

    widget.update()


def _generate_friendly_labels(fields: list[DetectedField]) -> list[DetectedField]:
    """
    Use DeepSeek to generate clean, user-friendly labels for form fields.

    Takes the full label_context and native field names and produces
    concise, descriptive labels for display.
    """
    try:
        import httpx
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")
        
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        
        # Create client without proxy to avoid conflicts with system proxy settings
        http_client = httpx.Client(proxy=None)
        client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

        # Prepare field summaries for the LLM
        field_summaries = []
        for i, field in enumerate(fields):
            # Include position AND size info to help LLM understand layout
            x_pos = field.bbox[0]  # x0
            y_pos = field.bbox[1]  # y0
            width = field.bbox[2] - field.bbox[0]  # x1 - x0
            height = field.bbox[3] - field.bbox[1]  # y1 - y0
            field_summaries.append({
                "index": i,
                "field_id": field.field_id,
                "field_type": field.field_type.value,
                "native_name": field.native_field_name,
                "position": f"page {field.page}, x={int(x_pos)}, y={int(y_pos)}",
                "size": f"width={int(width)}, height={int(height)}",  # Help identify multi-part fields
                "nearby_text": field.label_context,
            })

        prompt = f"""你是一个表单字段分析专家。请为每个表单字段生成简洁、清晰的**中文**标签。

## 理解 nearby_text 格式：
- "LEFT: ..." = 字段左侧的文本（通常是标签）
- "ABOVE: ..." = 字段上方的文本（可能是标签或标题）
- "RIGHT: ..." = 字段右侧的文本（多栏表单中可能不相关）
- "BELOW: ..." = 字段下方的文本

## 多部分字段识别（SSN、EIN、电话、日期）：
许多表单会将号码拆分成多个连续字段，你必须分别识别每个部分：

**社会安全号码 (SSN)** - 格式 XXX-XX-XXXX（3个字段）：
- 查找"Social security number"附近的3个小文本框
- 标签示例："社会安全号 第1部分（3位）"、"社会安全号 第2部分（2位）"、"社会安全号 第3部分（4位）"

**雇主识别号 (EIN)** - 格式 XX-XXXXXXX（2个字段）：
- 查找"Employer identification number"附近的2个文本框
- 标签示例："雇主识别号 第1部分（2位）"、"雇主识别号 第2部分（7位）"

## 识别多部分字段的方法：
1. 检查多个字段是否有相似的 y 坐标（同一行）
2. 检查它们是否有相似的 nearby_text（同一标签区域）
3. 检查宽度 - 较窄的字段 = 较少的数字
4. 按 x 坐标顺序排列的字段可能是同一号码的各部分

## 常见字段翻译参考：
- Name → 姓名
- Business name → 企业名称
- Address → 地址
- City, state, ZIP → 城市、州、邮编
- Exempt payee code → 豁免收款人代码
- FATCA exemption code → FATCA豁免代码
- Individual/sole proprietor → 个人/独资经营者
- Corporation → 公司
- Partnership → 合伙企业
- LLC → 有限责任公司
- Trust/estate → 信托/遗产
- Account number → 账户号码
- Signature → 签名
- Date → 日期

## 要求：
- 所有标签必须是**中文**
- 保持标签简洁但能区分多部分字段
- 对于 SSN/EIN，始终包含"第1部分"、"第2部分"等

待分析的字段：
{json.dumps(field_summaries, indent=2)}

请返回 JSON 对象，键为字段索引（字符串），值为中文友好标签。
示例：{{"0": "姓名", "1": "社会安全号 第1部分（3位）", "2": "社会安全号 第2部分（2位）", "3": "企业名称"}}"""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that returns valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
        )

        # Parse the response
        response_text = response.choices[0].message.content.strip()

        # Try to extract JSON from the response
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        labels_map = json.loads(response_text)

        # Apply the friendly labels
        for i, field in enumerate(fields):
            label = labels_map.get(str(i))
            if label:
                field.friendly_label = label
            else:
                # Fallback to native field name
                field.friendly_label = field.native_field_name

        return fields

    except Exception as e:
        print(f"Warning: Failed to generate friendly labels: {e}")
        # On error, fallback to native field names
        for field in fields:
            field.friendly_label = field.native_field_name
        return fields


# ============================================================================
# Utility for Testing
# ============================================================================

def get_form_summary(pdf_bytes: bytes) -> str:
    """
    Get a human-readable summary of form fields in a PDF.
    Useful for testing and debugging.
    """
    fields = detect_form_fields(pdf_bytes)

    if not fields:
        return "No fillable form fields detected in this PDF."

    lines = [f"Found {len(fields)} fillable form fields:\n"]

    for f in fields:
        lines.append(f"  - {f.field_id} ({f.field_type.value})")
        if f.friendly_label:
            lines.append(f"    Friendly Label: {f.friendly_label}")
        lines.append(f"    Context: {f.label_context[:100]}...")
        if f.current_value:
            lines.append(f"    Current value: {f.current_value}")
        if f.options:
            lines.append(f"    Options: {f.options}")
        lines.append("")

    return '\n'.join(lines)


if __name__ == "__main__":
    # Quick test - you can run this file directly to test
    import sys
    
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        print(get_form_summary(pdf_bytes))
    else:
        print("Usage: python pdf_processor.py <path_to_pdf>")
        print("\nThis will show all detected form fields in the PDF.")

