'use client';

import { ChatMessage as ChatMessageType } from '@/types';
import AgentActivityLog from './AgentActivityLog';

interface ChatMessageProps {
  message: ChatMessageType;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const isStreaming = message.status === 'streaming';
  const hasAgentLog = message.agentLog && message.agentLog.length > 0;

  if (isSystem) {
    return (
      <div className="flex justify-center animate-fadeIn">
        <div className="px-3 py-1.5 rounded-full bg-background-tertiary text-xs text-foreground-muted">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex gap-3 animate-fadeIn ${isUser ? 'justify-end' : 'justify-start'}`}>
      {/* Avatar */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-foreground flex items-center justify-center">
          <svg className="w-4 h-4 text-background" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
      )}

      {/* Message content */}
      <div className={`max-w-[85%] space-y-2 ${isUser ? 'items-end' : 'items-start'}`}>
        {/* User message bubble */}
        {isUser && (
          <div className="px-4 py-3 rounded-2xl bg-foreground text-background rounded-br-md">
            <div className="text-sm whitespace-pre-wrap">{message.content}</div>
          </div>
        )}

        {/* Assistant message */}
        {!isUser && (
          <>
            {/* Agent activity log (expandable) */}
            {(hasAgentLog || isStreaming) && (
              <AgentActivityLog
                entries={message.agentLog || []}
                currentStatus={isStreaming ? '正在处理您的请求...' : undefined}
                isStreaming={isStreaming}
              />
            )}

            {/* Final response content */}
            {message.content && message.status !== 'streaming' && (
              <div className="px-4 py-3 rounded-2xl bg-background-tertiary text-foreground rounded-bl-md">
                <div className="text-sm whitespace-pre-wrap">{message.content}</div>
              </div>
            )}

            {/* Error state */}
            {message.status === 'error' && (
              <div className="px-4 py-3 rounded-2xl bg-error/10 border border-error/20 text-error rounded-bl-md">
                <div className="text-sm whitespace-pre-wrap">{message.content}</div>
              </div>
            )}
          </>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-foreground-muted/20 flex items-center justify-center">
          <svg className="w-4 h-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
        </div>
      )}
    </div>
  );
}
