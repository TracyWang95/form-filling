# PDF Form Filler

An AI-powered application for filling PDF forms using natural language instructions. Built with DeepSeek LLM and OpenParse.

## Features

- **Natural Language Form Filling**: Describe what you want to fill, and the AI agent handles the rest
- **Multi-Turn Conversations**: Iteratively refine form edits across multiple messages
- **Context File Upload**: Upload reference documents (PDF, DOCX, PPTX, images) that the agent uses to extract information for filling forms
- **Real-Time Streaming**: Watch the agent's progress as it analyzes and fills your form
- **Session Persistence**: Sessions survive page reloads and server restarts (SQLite + file storage)
- **Dual PDF View**: Toggle between original and filled PDF views

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                          │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐ │
│  │ PDF Viewer  │  │ Chat Panel  │  │ Context Files Upload     │ │
│  └─────────────┘  └─────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ SSE Streaming
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐ │
│  │ PDF Process │  │ DeepSeek LLM│  │ OpenParse Integration    │ │
│  │ (PyMuPDF)   │  │ (OpenAI SDK)│  │ (Context File Parsing)   │ │
│  └─────────────┘  └─────────────┘  └──────────────────────────┘ │
│                         │                                        │
│                         ▼                                        │
│              ┌──────────────────────┐                           │
│              │  Session Manager     │                           │
│              │  (SQLite + Files)    │                           │
│              └──────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- DeepSeek API key (required for LLM functionality)
- OpenParse (open-source, no API key needed for parsing)

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repo-url>
cd form-filling-exp

# Create Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd web
npm install
cd ..
```

### 2. Environment Variables

```bash
# Required: DeepSeek API key
export DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here

# Optional: Custom DeepSeek API endpoint (default: https://api.deepseek.com)
export DEEPSEEK_BASE_URL=https://api.deepseek.com

# Optional: DeepSeek model (default: deepseek-chat)
export DEEPSEEK_MODEL=deepseek-chat
```

**获取 DeepSeek API 密钥：**
1. 访问 [DeepSeek 平台](https://platform.deepseek.com/)
2. 注册/登录账号
3. 进入 [API Keys 页面](https://platform.deepseek.com/api_keys)
4. 创建新的 API 密钥

### 3. Run the Application

```bash
# Terminal 1: Start the backend
cd backend
python main.py
# Backend runs on http://localhost:8000

# Terminal 2: Start the frontend
cd web
npm run dev
# Frontend runs on http://localhost:3000
```

Open http://localhost:3000 in your browser.

## Project Structure

```
.
├── backend/
│   ├── main.py           # FastAPI server with SSE streaming endpoints
│   ├── agent_deepseek.py # DeepSeek agent with function calling tools
│   ├── pdf_processor.py  # PDF field detection and editing (PyMuPDF)
│   ├── parser.py         # OpenParse integration for context files
│   ├── llm.py            # Structured output LLM for simple fills
│   ├── sessions.db       # SQLite database for session persistence
│   └── sessions_data/    # PDF file storage for sessions
├── web/
│   ├── src/
│   │   ├── app/
│   │   │   └── page.tsx          # Main application page
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx     # Chat interface with agent
│   │   │   ├── ContextFilesUpload.tsx  # Context file upload UI
│   │   │   ├── PdfViewer.tsx     # PDF preview component
│   │   │   └── ...
│   │   └── lib/
│   │       ├── api.ts            # Backend API client
│   │       └── session.ts        # Session persistence helpers
│   └── package.json
├── requirements.txt
└── README.md
```

## Usage

### Basic Form Filling

1. **Upload a PDF**: Drag and drop or click to upload a PDF with fillable form fields
2. **Enter Instructions**: Type natural language instructions like:
   - "My name is John Doe, email john@example.com"
   - "Fill all date fields with today's date"
   - "Check all the boxes"
3. **Watch the Agent**: See real-time progress as the agent analyzes fields and fills them
4. **Download**: Click the download button to get your filled PDF

### Using Context Files

For complex forms, upload reference documents that contain the information to fill:

1. **Upload Context Files**: In the chat panel, upload up to 5 files (PDF, DOCX, PPTX, images, or text files)
2. **Choose Parse Mode**:
   - **Fast**: Faster parsing for most documents
   - **Detailed**: Higher quality extraction for complex documents
3. **Reference in Instructions**: "Fill the form using the information from my resume"

### Multi-Turn Editing

Continue refining your form across multiple messages:

- "Change the phone number to 555-1234"
- "Uncheck the marketing consent box"
- "Update the address to 456 Oak St"

The agent remembers previous edits and only modifies what you ask.

## API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | POST | Analyze PDF and detect form fields |
| `/fill-agent-stream` | POST | Fill form with streaming agent (SSE) |
| `/parse-files` | POST | Parse context files with OpenParse (SSE) |

### Session Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/session/{id}` | GET | Get session info |
| `/session/{id}/pdf` | GET | Get filled PDF bytes |
| `/session/{id}/original-pdf` | GET | Get original PDF bytes |
| `/session/{id}/context-files` | GET | Get parsed context files |

### Utility Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/parse-status` | GET | Check OpenParse availability |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger API documentation |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | No | DeepSeek API base URL (default: https://api.deepseek.com) |
| `DEEPSEEK_MODEL` | No | DeepSeek model (default: deepseek-chat) |

### OpenParse Modes

| Mode | Description | Best For |
|------|-------------|----------|
| `fast` | Faster parsing | Most documents |
| `detailed` | Higher quality extraction | Complex layouts, tables |

## Technical Details

### DeepSeek Agent

The application uses a DeepSeek-based agent with custom tools for form filling:

- `load_pdf` - Load and analyze a PDF
- `list_all_fields` - Get all form fields
- `search_fields` - Search fields by query
- `set_field` - Stage a field edit
- `commit_edits` - Apply all staged edits

### Session Persistence

Sessions are persisted using:
- **SQLite**: Metadata, applied edits, context files (JSON)
- **File System**: PDF bytes (original and filled)
- **Frontend localStorage**: Session ID mapping

### Supported File Types

**Form PDFs**: Must have native AcroForm fields (fillable fields)

**Context Files**:
- Documents: PDF, DOCX, PPTX, DOC, PPT, XLSX, XLS
- Images: PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP
- Text: TXT, MD, CSV, JSON, XML, HTML, and code files

## Limitations

- Only works with PDFs that have native AcroForm fields
- Does not support OCR or drawing on flat PDFs
- Context file parsing uses OpenParse (no API key required)

## Development

```bash
# Run backend with auto-reload
cd backend
uvicorn main:app --reload --port 8000

# Run frontend with hot-reload
cd web
npm run dev

# Build frontend for production
cd web
npm run build
```

## License

MIT
