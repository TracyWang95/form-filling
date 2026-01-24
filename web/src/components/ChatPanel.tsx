'use client';

import { useState, useRef, useEffect } from 'react';
import { ChatMessage as ChatMessageType } from '@/types';
import ChatMessage from './ChatMessage';
import ContextFilesUpload, { ContextFile, ParseProgress } from './ContextFilesUpload';
import VoiceInput from './VoiceInput';

interface ChatPanelProps {
  messages: ChatMessageType[];
  onSendMessage: (message: string) => void;
  onClearMessages?: () => void;
  isProcessing: boolean;
  disabled?: boolean;
  statusMessage?: string;
  contextFiles?: ContextFile[];
  onContextFilesChange?: (files: ContextFile[]) => void;
  onParseFiles?: (files: File[], parseMode: 'cost_effective' | 'agentic_plus') => Promise<void>;
  isUploadingContext?: boolean;
  parseProgress?: ParseProgress | null;
  appliedEditsCount?: number;
}

export default function ChatPanel({
  messages,
  onSendMessage,
  onClearMessages,
  isProcessing,
  disabled,
  statusMessage,
  contextFiles = [],
  onContextFilesChange,
  onParseFiles,
  isUploadingContext = false,
  parseProgress = null,
  appliedEditsCount = 0,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    if (!disabled) {
      inputRef.current?.focus();
    }
  }, [disabled]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isProcessing && !disabled) {
      onSendMessage(input.trim());
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border glass">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold tracking-wide">对话</h2>
            <p className="text-xs text-foreground-muted">
              {appliedEditsCount > 0 
                ? `已填写 ${appliedEditsCount} 个字段，继续输入可修改`
                : '用自然语言描述您要填写的内容'}
            </p>
          </div>
          {messages.length > 0 && onClearMessages && (
            <button
              onClick={onClearMessages}
              disabled={isProcessing}
              className="px-3 py-1.5 text-xs rounded-lg border border-border text-foreground-muted hover:text-foreground hover:bg-foreground/5 transition-colors disabled:opacity-50"
              title="清除对话记录"
            >
              清除对话
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-12 h-12 rounded-full bg-foreground/5 flex items-center justify-center mb-4 animate-glow">
              <svg className="w-6 h-6 text-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <h3 className="text-sm font-medium text-foreground-secondary mb-1">
              开始对话
            </h3>
            <p className="text-xs text-foreground-muted max-w-[200px]">
              上传 PDF 并描述您想要填写的内容
            </p>

            {/* Example prompts */}
            <div className="mt-6 space-y-2 w-full max-w-[280px]">
              <p className="text-xs text-foreground-muted">试试这样说：</p>
              {[
                '我叫张三，手机号 13800138000',
                '把日期填成今天，勾选所有复选框',
                '地址：北京市朝阳区建国路100号',
              ].map((example, idx) => (
                <button
                  key={idx}
                  onClick={() => setInput(example)}
                  disabled={disabled}
                  className="w-full text-left px-3 py-2 text-xs rounded-lg bg-foreground/5 text-foreground-secondary hover:bg-foreground/10 transition-colors disabled:opacity-50 border border-border"
                >
                  「{example}」
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}

        {/* Status indicator */}
        {isProcessing && statusMessage && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-foreground/5 text-foreground text-sm animate-fadeIn border border-border">
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
            {statusMessage}
          </div>
        )}
      </div>

      {/* Context Files Upload */}
      {onContextFilesChange && onParseFiles && (
        <div className="px-4 py-3 border-t border-border">
          <ContextFilesUpload
            files={contextFiles}
            onFilesChange={onContextFilesChange}
            onParseFiles={onParseFiles}
            isUploading={isUploadingContext}
            parseProgress={parseProgress}
            disabled={disabled || isProcessing}
          />
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-border">
        <div className="relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? '请先上传 PDF 文件...' : '输入您的填表指令...'}
            disabled={disabled || isProcessing}
            rows={3}
            className="w-full px-4 py-3 pr-24 rounded-xl bg-background-tertiary border border-border text-sm text-foreground placeholder:text-foreground-muted resize-none focus:outline-none focus:ring-2 focus:ring-foreground/20 focus:border-foreground/30 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          />
          <div className="absolute right-3 bottom-3 flex items-center gap-2">
            <VoiceInput 
              onTranscript={(text) => setInput(prev => prev ? `${prev} ${text}` : text)}
              disabled={disabled || isProcessing}
            />
            <button
              type="submit"
              disabled={!input.trim() || isProcessing || disabled}
              className="p-2 rounded-lg bg-foreground text-background hover:bg-foreground-secondary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? (
                <div className="w-4 h-4 border-2 border-background border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-foreground-muted">
          按 Enter 发送，Shift+Enter 换行，点击麦克风语音输入
        </p>
      </form>
    </div>
  );
}
