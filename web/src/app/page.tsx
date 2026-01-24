'use client';

import { useState, useCallback, useEffect } from 'react';
import { ChatMessage, FormField, PdfDisplayMode, StreamEvent, AgentLogEntry } from '@/types';
import { analyzePdf, streamAgentFill, hexToBytes, getSessionPdf, getSessionOriginalPdf, streamParseFiles, getSessionContextFiles } from '@/lib/api';
import { ContextFile, ParseProgress } from '@/components/ContextFilesUpload';
import {
  createSession,
  createMessage,
  getSessionIdFromUrl,
  setSessionIdInUrl,
  saveSessionToStorage,
  loadSessionFromStorage,
} from '@/lib/session';
import LeftPanel from '@/components/LeftPanel';
import ChatPanel from '@/components/ChatPanel';
import ApiKeyGate, { clearStoredApiKey } from '@/components/ApiKeyGate';

// Helper to generate unique IDs
const generateId = () => Math.random().toString(36).substring(2, 11);

export default function Home() {
  // DeepSeek API key (required to use the app)
  const [deepseekApiKey, setDeepseekApiKey] = useState<string | null>(null);

  const [sessionId, setSessionId] = useState<string>('');
  const [file, setFile] = useState<File | null>(null);
  const [fields, setFields] = useState<FormField[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [originalPdfBytes, setOriginalPdfBytes] = useState<Uint8Array | null>(null);  // For restored sessions
  const [filledPdfBytes, setFilledPdfBytes] = useState<Uint8Array | null>(null);
  const [pdfDisplayMode, setPdfDisplayMode] = useState<PdfDisplayMode>('original');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  // Track applied edits for multi-turn conversations
  const [appliedEdits, setAppliedEdits] = useState<Record<string, unknown> | null>(null);
  // Track agent session ID for resuming conversations
  const [agentSessionId, setAgentSessionId] = useState<string | null>(null);
  // Track user session ID for backend state isolation (concurrent user support)
  const [userSessionId, setUserSessionId] = useState<string | null>(null);
  // Context files for the agent
  const [contextFiles, setContextFiles] = useState<ContextFile[]>([]);
  const [isUploadingContext, setIsUploadingContext] = useState(false);
  const [parseProgress, setParseProgress] = useState<ParseProgress | null>(null);

  // Initialize session from URL or create new one
  useEffect(() => {
    const urlSessionId = getSessionIdFromUrl();

    if (urlSessionId) {
      // Try to load existing session
      const stored = loadSessionFromStorage(urlSessionId);
      console.log('[DEBUG] Loading session from storage:', {
        urlSessionId,
        stored: stored ? { hasFields: stored.fields?.length, hasMessages: stored.messages?.length, userSessionId: stored.userSessionId } : null,
      });
      if (stored) {
        setSessionId(urlSessionId);
        setFields(stored.fields || []);
        setMessages(stored.messages || []);

        // If we have a userSessionId, try to fetch both PDFs from backend
        if (stored.userSessionId) {
          console.log('[DEBUG] Fetching PDFs from backend for userSessionId:', stored.userSessionId);
          setUserSessionId(stored.userSessionId);

          // Fetch both original and filled PDFs and context files in parallel
          Promise.all([
            getSessionPdf(stored.userSessionId),
            getSessionOriginalPdf(stored.userSessionId),
            getSessionContextFiles(stored.userSessionId),
          ]).then(([filledBytes, originalBytes, contextFilesData]) => {
            console.log('[DEBUG] Session fetch results:', {
              hasFilledBytes: !!filledBytes,
              filledSize: filledBytes?.length,
              hasOriginalBytes: !!originalBytes,
              originalSize: originalBytes?.length,
              contextFilesCount: contextFilesData?.length,
            });
            if (filledBytes) {
              setFilledPdfBytes(filledBytes);
              setPdfDisplayMode('filled');
            }
            if (originalBytes) {
              setOriginalPdfBytes(originalBytes);
            }
            if (contextFilesData) {
              setContextFiles(contextFilesData.map(f => ({
                filename: f.filename,
                content: f.content,
                was_parsed: f.was_parsed,
              })));
            }
          });
        }
      } else {
        // Session not found, create new one
        const session = createSession();
        setSessionId(session.id);
        setSessionIdInUrl(session.id);
      }
    } else {
      // No session in URL, create new one
      const session = createSession();
      setSessionId(session.id);
      setSessionIdInUrl(session.id);
    }
  }, []);

  // Save session to storage when it changes
  useEffect(() => {
    if (sessionId) {
      saveSessionToStorage(
        {
          id: sessionId,
          originalPdf: file,
          filledPdfBytes,
          fields,
          messages,
          isProcessing,
        },
        userSessionId
      );
    }
  }, [sessionId, fields, messages, file, filledPdfBytes, isProcessing, userSessionId]);

  // Handle file selection and analysis
  const handleFileSelect = useCallback(async (selectedFile: File | null) => {
    if (!selectedFile) {
      setFile(null);
      setFields([]);
      setOriginalPdfBytes(null);  // Clear restored original PDF
      setFilledPdfBytes(null);
      setPdfDisplayMode('original');
      setAppliedEdits(null);  // Clear edits when resetting
      setAgentSessionId(null);  // Clear agent session when resetting
      setUserSessionId(null);  // Clear user session when resetting
      setContextFiles([]);  // Clear context files when resetting
      return;
    }

    setFile(selectedFile);
    setOriginalPdfBytes(null);  // Clear restored original PDF for new file
    setFilledPdfBytes(null);
    setPdfDisplayMode('original');
    setAppliedEdits(null);  // Clear edits for new file
    setAgentSessionId(null);  // Clear agent session for new file
    setUserSessionId(null);  // Clear user session for new file
    setContextFiles([]);  // Clear context files for new file
    setIsAnalyzing(true);

    try {
      const result = await analyzePdf(selectedFile);
      setFields(result.fields);

      // Add system message about detected fields
      if (result.field_count > 0) {
        setMessages((prev) => [
          ...prev,
          createMessage('system', `检测到 ${result.field_count} 个可填写字段`),
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          createMessage('system', '未检测到可填写的表单字段。请确保这是包含 AcroForm 字段的 PDF 文件。'),
        ]);
      }
    } catch (error) {
      console.error('Analysis error:', error);
      setMessages((prev) => [
        ...prev,
        createMessage('system', `PDF 分析错误: ${error instanceof Error ? error.message : '未知错误'}`),
      ]);
    } finally {
      setIsAnalyzing(false);
    }
  }, []);

  // Handle clearing chat messages
  const handleClearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  // Handle creating a new session (completely fresh start)
  const handleNewSession = useCallback(() => {
    // Clear URL session parameter
    const url = new URL(window.location.href);
    url.searchParams.delete('session');
    window.history.replaceState({}, '', url.toString());
    // Reload to start fresh
    window.location.reload();
  }, []);

  // Handle parsing context files
  const handleParseFiles = useCallback(
    async (files: File[], parseMode: 'fast' | 'detailed') => {
      setIsUploadingContext(true);
      setParseProgress(null);

      // Generate a userSessionId if one doesn't exist yet
      // This ensures context files can be stored in the backend session
      let currentUserSessionId = userSessionId;
      if (!currentUserSessionId) {
        currentUserSessionId = generateId() + '-' + Date.now();
        setUserSessionId(currentUserSessionId);
      }

      try {
        const results: ContextFile[] = [];

        for await (const event of streamParseFiles(files, parseMode, deepseekApiKey!, currentUserSessionId)) {
          if (event.type === 'progress' && event.current !== undefined && event.total !== undefined && event.filename && event.status) {
            setParseProgress({
              current: event.current,
              total: event.total,
              filename: event.filename,
              status: event.status,
              error: event.error,
            });
          }

          if (event.type === 'complete' && event.results) {
            for (const result of event.results) {
              if (result.content && !result.error) {
                results.push({
                  filename: result.filename,
                  content: result.content,
                  was_parsed: result.parsed,
                });
              }
            }
          }
        }

        // Add new files to existing context files
        setContextFiles((prev) => [...prev, ...results]);
      } catch (error) {
        console.error('Parse files error:', error);
        setMessages((prev) => [
          ...prev,
          createMessage('system', `文件解析错误: ${error instanceof Error ? error.message : '未知错误'}`),
        ]);
      } finally {
        setIsUploadingContext(false);
        setParseProgress(null);
      }
    },
    [userSessionId, deepseekApiKey]
  );

  // Handle sending a chat message
  const handleSendMessage = useCallback(
    async (content: string) => {
      if (!file) {
        setMessages((prev) => [
          ...prev,
          createMessage('system', '请先上传 PDF 文件'),
        ]);
        return;
      }

      // Add user message
      const userMessage = createMessage('user', content);
      setMessages((prev) => [...prev, userMessage]);

      // Create assistant message placeholder with empty agent log
      const assistantMessage: ChatMessage = {
        ...createMessage('assistant', '', 'streaming'),
        agentLog: [],
      };
      setMessages((prev) => [...prev, assistantMessage]);

      setIsProcessing(true);
      setStatusMessage('正在启动智能助手...');

      // Determine if this is a continuation (we have a previous agent session)
      const isContinuation = Boolean(agentSessionId && filledPdfBytes);

      let finalContent = '';
      let appliedCount = 0;
      let newAppliedEdits: Record<string, unknown> | null = null;
      let newAgentSessionId: string | null = null;
      let newUserSessionId: string | null = null;
      let newFilledPdfBytes: Uint8Array | null = null;

      try {
        for await (const event of streamAgentFill({
          file,
          instructions: content,
          filledPdfBytes: isContinuation ? filledPdfBytes : null,
          isContinuation,
          previousEdits: appliedEdits,
          resumeSessionId: agentSessionId,
          userSessionId: userSessionId,
        })) {
          const logEntry = createLogEntry(event);

          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantMessage.id) return m;

              const updatedLog = logEntry
                ? [...(m.agentLog || []), logEntry]
                : m.agentLog;

              // Update status message for UI
              if (logEntry) {
                setStatusMessage(logEntry.content);
              }

              return {
                ...m,
                agentLog: updatedLog,
              };
            })
          );

          // Handle special events
          if (event.type === 'complete') {
            appliedCount = event.applied_count || 0;
            // Track all applied edits for multi-turn
            if (event.applied_edits) {
              newAppliedEdits = event.applied_edits;
            }
            // Track agent session ID for resuming conversations
            if (event.session_id) {
              newAgentSessionId = event.session_id;
            }
            // Track user session ID for backend state isolation
            if (event.user_session_id) {
              newUserSessionId = event.user_session_id;
            }
            const totalEdits = newAppliedEdits ? Object.keys(newAppliedEdits).length : appliedCount;
            if (isContinuation) {
              finalContent = `已更新 ${appliedCount} 个字段。累计填写: ${totalEdits} 个字段。`;
            } else {
              finalContent = `成功填写 ${appliedCount} 个表单字段。`;
            }
          }

          if (event.type === 'pdf_ready' && event.pdf_bytes) {
            const bytes = hexToBytes(event.pdf_bytes);
            newFilledPdfBytes = bytes;
            setFilledPdfBytes(bytes);
            setPdfDisplayMode('filled');
          }

          if (event.type === 'error') {
            finalContent = event.error || '发生错误';
          }
        }

        // Update applied edits after successful completion
        if (newAppliedEdits) {
          setAppliedEdits(newAppliedEdits);
        }

        // Update agent session ID for multi-turn conversations
        if (newAgentSessionId) {
          setAgentSessionId(newAgentSessionId);
        }

        // Update user session ID for backend state isolation
        // IMPORTANT: Save to localStorage immediately to ensure it persists even if the tab is closed quickly
        if (newUserSessionId) {
          console.log('[DEBUG] Saving userSessionId to localStorage:', {
            sessionId,
            newUserSessionId,
            hasFields: fields.length,
          });
          setUserSessionId(newUserSessionId);
          // Immediate save to localStorage to prevent data loss on quick tab close
          // Use newFilledPdfBytes since state updates are async
          saveSessionToStorage(
            {
              id: sessionId,
              originalPdf: file,
              filledPdfBytes: newFilledPdfBytes || filledPdfBytes,
              fields,
              messages,
              isProcessing: false,
            },
            newUserSessionId
          );
        }

        // Mark assistant message as complete
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? {
                  ...m,
                  status: 'complete',
                  content: finalContent || `已填写 ${appliedCount} 个字段。`,
                }
              : m
          )
        );
      } catch (error) {
        console.error('Agent error:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';

        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? {
                  ...m,
                  status: 'error',
                  content: `Error: ${errorMessage}`,
                  agentLog: [
                    ...(m.agentLog || []),
                    {
                      id: generateId(),
                      type: 'error' as const,
                      timestamp: new Date(),
                      content: errorMessage,
                    },
                  ],
                }
              : m
          )
        );
      } finally {
        setIsProcessing(false);
        setStatusMessage('');
      }
    },
    [file, filledPdfBytes, appliedEdits, agentSessionId, userSessionId, sessionId, fields, messages]
  );

  return (
    <ApiKeyGate onApiKeyValidated={setDeepseekApiKey}>
    <div className="h-screen flex flex-col bg-background">
      {/* Header */}
      <header className="flex-shrink-0 px-6 py-3 border-b border-border flex items-center justify-between glass">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-foreground flex items-center justify-center">
            <svg className="w-5 h-5 text-background" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-wide">智能填表</h1>
            <p className="text-xs text-foreground-muted">自然语言交互式 PDF 表单填写</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {sessionId && (
            <div className="text-xs text-foreground-muted font-mono">
              会话: {sessionId.slice(0, 8)}...
            </div>
          )}
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            className="text-xs text-foreground-muted hover:text-foreground transition-colors"
          >
            接口文档
          </a>
          <button
            onClick={() => {
              clearStoredApiKey();
              setDeepseekApiKey(null);
              window.location.reload();
            }}
            className="text-xs text-foreground-muted hover:text-error transition-colors"
            title="退出登录并清除 API 密钥"
          >
            退出
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel - PDF upload and preview */}
        <div className="w-1/2 border-r border-border flex flex-col overflow-hidden">
          <LeftPanel
            file={file}
            onFileSelect={handleFileSelect}
            onNewSession={handleNewSession}
            fields={fields}
            originalPdfBytes={originalPdfBytes}
            filledPdfBytes={filledPdfBytes}
            pdfDisplayMode={pdfDisplayMode}
            onPdfDisplayModeChange={setPdfDisplayMode}
            isAnalyzing={isAnalyzing}
            isProcessing={isProcessing}
          />
        </div>

        {/* Right panel - Chat interface */}
        <div className="w-1/2 flex flex-col overflow-hidden">
          <ChatPanel
            messages={messages}
            onSendMessage={handleSendMessage}
            onClearMessages={handleClearMessages}
            isProcessing={isProcessing}
            disabled={!file || fields.length === 0}
            statusMessage={statusMessage}
            contextFiles={contextFiles}
            onContextFilesChange={setContextFiles}
            onParseFiles={handleParseFiles}
            isUploadingContext={isUploadingContext}
            parseProgress={parseProgress}
            appliedEditsCount={appliedEdits ? Object.keys(appliedEdits).length : 0}
          />
        </div>
      </main>
    </div>
    </ApiKeyGate>
  );
}

// Create a log entry from a stream event
function createLogEntry(event: StreamEvent): AgentLogEntry | null {
  const id = generateId();
  const timestamp = new Date();

  switch (event.type) {
    case 'init':
      return {
        id,
        type: 'status',
        timestamp,
        content: event.message || '正在初始化...',
      };

    case 'status':
      return {
        id,
        type: 'status',
        timestamp,
        content: event.message || '处理中...',
      };

    case 'tool_use':
      if (event.friendly && event.friendly.length > 0) {
        // Ensure friendly is an array (might be string from DeepSeek agent)
        const friendlyArray = Array.isArray(event.friendly) ? event.friendly : [event.friendly];
        // Clean up markdown formatting
        const cleanedActions = friendlyArray.map((f) => f.replace(/\*\*/g, ''));

        if (friendlyArray.length > 1) {
          return {
            id,
            type: 'tool_call',
            timestamp,
            content: `正在填写 ${friendlyArray.length} 个字段`,
            details: cleanedActions.join(', '),
          };
        } else {
          return {
            id,
            type: 'tool_call',
            timestamp,
            content: cleanedActions[0],
          };
        }
      }
      return null;

    case 'user':
      // Tool results - event.friendly might be string[] or string from DeepSeek agent
      if (event.friendly && event.friendly.length > 0) {
        const friendlyArray = Array.isArray(event.friendly) ? event.friendly : [event.friendly];
        return {
          id,
          type: 'tool_result',
          timestamp,
          content: friendlyArray.join(', '),
        };
      }
      return null;

    case 'assistant':
      if (event.text) {
        return {
          id,
          type: 'thinking',
          timestamp,
          content: '智能助手思考中...',
          details: event.text.slice(0, 100) + (event.text.length > 100 ? '...' : ''),
        };
      }
      return null;

    case 'complete':
      return {
        id,
        type: 'complete',
        timestamp,
        content: `已完成 - 填写了 ${event.applied_count || 0} 个字段`,
      };

    case 'error':
      return {
        id,
        type: 'error',
        timestamp,
        content: event.error || '发生错误',
      };

    case 'pdf_ready':
      return {
        id,
        type: 'complete',
        timestamp,
        content: '表单填写成功',
      };

    default:
      return null;
  }
}
