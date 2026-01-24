# 运行指南

本文档说明如何运行修改后的项目（使用 DeepSeek 和 OpenParse）。

## 前置要求

- Python 3.10+
- Node.js 18+
- DeepSeek API 密钥（必需，用于 LLM 功能）

## 快速开始

### 1. 安装依赖

#### Python 后端依赖

```bash
# 进入项目目录
cd form-filling-exp

# 创建 Python 虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

#### 前端依赖

```bash
# 进入 web 目录
cd web

# 安装 Node.js 依赖
npm install

# 返回根目录
cd ..
```

### 2. 配置环境变量

#### 方法 1: 使用 .env 文件（推荐）⭐

这是最简单的方法，**无需在命令行设置环境变量**：

1. **复制示例文件并编辑**：
   ```bash
   # Linux/Mac
   cp .env.example .env
   
   # Windows PowerShell
   Copy-Item .env.example .env
   
   # Windows CMD
   copy .env.example .env
   ```

2. **编辑 `.env` 文件**，填入您的 API 密钥：
   ```
   DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-chat
   ```

3. **安装 python-dotenv**（如果还没有安装）：
   ```bash
   pip install python-dotenv
   ```

   ✅ **完成！代码会自动从 .env 文件加载环境变量。**

#### 方法 2: 命令行设置（临时）

**Linux/Mac (bash/zsh):**
```bash
export DEEPSEEK_API_KEY="sk-your-deepseek-api-key-here"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"
```

**Windows PowerShell:**
```powershell
$env:DEEPSEEK_API_KEY="sk-your-deepseek-api-key-here"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-chat"
```

**Windows CMD:**
```cmd
set DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
set DEEPSEEK_BASE_URL=https://api.deepseek.com
set DEEPSEEK_MODEL=deepseek-chat
```

> **⚠️ Windows 用户注意**：`export` 命令在 Windows PowerShell 中不可用！请使用上述 Windows 特定命令，或直接使用 .env 文件（推荐）。

> 📖 **详细说明**：查看 [WINDOWS_SETUP.md](WINDOWS_SETUP.md) 获取 Windows 环境变量设置的完整指南。

### 3. 获取 DeepSeek API 密钥

1. 访问 [DeepSeek 平台](https://platform.deepseek.com/)
2. 注册/登录账号
3. 进入 [API Keys 页面](https://platform.deepseek.com/api_keys)
4. 创建新的 API 密钥
5. 复制密钥并设置到环境变量中

### 4. 运行应用

#### 方式 1: 使用开发模式（推荐）

**终端 1 - 启动后端服务器：**

```bash
# 确保已激活虚拟环境
cd backend

# 运行后端（带自动重载）
uvicorn main:app --reload

# 或者直接运行
python main.py
```

后端将在 `http://localhost:8000` 运行。

**终端 2 - 启动前端开发服务器：**

```bash
cd web
npm run dev
```

前端将在 `http://localhost:3000` 运行。

#### 方式 2: 使用生产模式

**后端：**
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

**前端：**
```bash
cd web
npm run build
npm start
```

### 5. 访问应用

打开浏览器访问：`http://localhost:3000`

首次访问时，应用会要求输入 DeepSeek API 密钥。密钥会保存在浏览器本地存储中。

## API 端点

后端提供以下主要端点：

- `POST /analyze` - 分析 PDF 表单字段
- `POST /fill-agent-stream` - 使用 AI 填充表单（流式响应）
- `POST /parse-files` - 解析上下文文件（使用 OpenParse）
- `POST /validate-api-key` - 验证 DeepSeek API 密钥
- `GET /health` - 健康检查
- `GET /docs` - API 文档（Swagger UI）

访问 `http://localhost:8000/docs` 查看完整的 API 文档。

## 故障排除

### 1. OpenParse 安装问题

如果遇到 OpenParse 安装错误，可以尝试：

```bash
# 更新 pip
pip install --upgrade pip

# 尝试从 GitHub 安装
pip install git+https://github.com/kolenaIO/openparse.git

# 或者使用替代的 PDF 解析库
# 如果 openparse 不可用，可以考虑使用 pymupdf (fitz) 或其他库
```

### 2. DeepSeek API 错误

如果遇到 API 认证错误：

- 检查 `DEEPSEEK_API_KEY` 是否正确设置
- 确认 API 密钥有效且未过期
- 检查网络连接是否正常
- 查看 DeepSeek 平台的服务状态

### 3. 端口占用

如果端口 8000 或 3000 被占用：

**后端更改端口：**
```bash
uvicorn main:app --port 8001
```

**前端更改端口：**
```bash
cd web
# 编辑 package.json 或使用环境变量
PORT=3001 npm run dev
```

### 4. 依赖冲突

如果遇到 Python 依赖冲突：

```bash
# 重新创建虚拟环境
deactivate  # 退出当前环境
rm -rf .venv  # 删除旧环境（Windows: rmdir /s .venv）
python -m venv .venv  # 创建新环境
source .venv/bin/activate  # 重新激活（Windows: .venv\Scripts\activate）
pip install -r requirements.txt  # 重新安装
```

## 开发提示

### 后端开发

- 使用 `uvicorn main:app --reload` 启用自动重载
- 查看日志输出以调试问题
- 使用 `http://localhost:8000/docs` 测试 API

### 前端开发

- 使用 `npm run dev` 启用热重载
- 浏览器开发者工具查看网络请求
- 检查控制台错误信息

### 测试

```bash
# 测试后端 API
curl http://localhost:8000/health

# 测试 API 密钥验证
curl -X POST http://localhost:8000/validate-api-key \
  -F "api_key=your-key-here"
```

## 注意事项

1. **OpenParse**: 这是开源库，不需要 API 密钥，但可能需要根据实际 API 调整代码
2. **DeepSeek**: 使用 OpenAI 兼容的 API，因此使用 `openai` Python 包
3. **Agent 实现**: 项目现在使用基于 DeepSeek 的自定义 agent (`agent_deepseek.py`)
4. **会话存储**: 会话数据存储在 `backend/sessions.db` 和 `backend/sessions_data/` 目录中
5. **工具调用**: Agent 使用 OpenAI 的函数调用 (function calling) 功能来实现表单填充工具

## 下一步

- 查看 `README.md` 了解项目架构
- 查看 `backend/main.py` 了解 API 端点
- 查看 `web/src/app/page.tsx` 了解前端实现
