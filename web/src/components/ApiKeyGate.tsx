'use client';

import { useState, useEffect } from 'react';
import { validateApiKey } from '@/lib/api';

const API_KEY_STORAGE_KEY = 'deepseek-api-key';

interface ApiKeyGateProps {
  children: React.ReactNode;
  onApiKeyValidated: (apiKey: string) => void;
}

export default function ApiKeyGate({ children, onApiKeyValidated }: ApiKeyGateProps) {
  const [apiKey, setApiKey] = useState('');
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isValidated, setIsValidated] = useState(false);
  const [isCheckingStored, setIsCheckingStored] = useState(true);

  // Check for stored API key on mount
  useEffect(() => {
    const storedKey = localStorage.getItem(API_KEY_STORAGE_KEY);
    if (storedKey) {
      // Validate the stored key
      setIsValidating(true);
      validateApiKey(storedKey)
        .then(() => {
          setIsValidated(true);
          onApiKeyValidated(storedKey);
        })
        .catch(() => {
          // Stored key is invalid, clear it
          localStorage.removeItem(API_KEY_STORAGE_KEY);
        })
        .finally(() => {
          setIsCheckingStored(false);
          setIsValidating(false);
        });
    } else {
      setIsCheckingStored(false);
    }
  }, [onApiKeyValidated]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!apiKey.trim()) {
      setError('请输入 API 密钥');
      return;
    }

    setIsValidating(true);
    setError(null);

    try {
      await validateApiKey(apiKey.trim());
      // Store the key
      localStorage.setItem(API_KEY_STORAGE_KEY, apiKey.trim());
      setIsValidated(true);
      onApiKeyValidated(apiKey.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'API 密钥验证失败');
    } finally {
      setIsValidating(false);
    }
  };

  // Show loading while checking stored key
  if (isCheckingStored) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-foreground-muted">
          <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
          <span>加载中...</span>
        </div>
      </div>
    );
  }

  // Show main app if validated
  if (isValidated) {
    return <>{children}</>;
  }

  // Show API key entry form
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        {/* Logo/Header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-foreground flex items-center justify-center mx-auto mb-4 animate-glow">
            <svg className="w-8 h-8 text-background" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-foreground tracking-wide">智能填表</h1>
          <p className="text-foreground-muted mt-2">自然语言交互式 PDF 表单填写</p>
        </div>

        {/* API Key Form */}
        <div className="bg-background-secondary rounded-xl p-6 border border-border shadow-sm">
          <h2 className="text-lg font-semibold text-foreground mb-2">输入您的 API 密钥</h2>
          <p className="text-sm text-foreground-muted mb-6">
            本应用需要 DeepSeek API 密钥才能使用。您的密钥仅保存在本地，不会发送到我们的服务器。
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="apiKey" className="block text-sm font-medium text-foreground-secondary mb-2">
                DeepSeek API 密钥
              </label>
              <input
                id="apiKey"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                disabled={isValidating}
                className="w-full px-4 py-3 rounded-lg bg-background border border-border text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-foreground/20 focus:border-foreground/30 disabled:opacity-50 transition-all"
              />
            </div>

            {error && (
              <div className="px-4 py-3 rounded-lg bg-error/10 border border-error/20 text-error text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isValidating || !apiKey.trim()}
              className="w-full px-4 py-3 rounded-lg bg-foreground text-background font-medium hover:bg-foreground-secondary disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {isValidating ? (
                <>
                  <div className="w-4 h-4 border-2 border-background border-t-transparent rounded-full animate-spin" />
                  验证中...
                </>
              ) : (
                '继续'
              )}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-border space-y-2">
            <p className="text-xs text-foreground-muted text-center">
              还没有账号？{' '}
              <a
                href="https://platform.deepseek.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground hover:underline font-medium"
              >
                注册 DeepSeek
              </a>
            </p>
            <p className="text-xs text-foreground-muted text-center">
              需要帮助获取 API 密钥？{' '}
              <a
                href="https://platform.deepseek.com/api_keys"
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground hover:underline font-medium"
              >
                查看文档
              </a>
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="text-xs text-foreground-muted text-center mt-6">
          由 DeepSeek 和 OpenParse 提供技术支持
        </p>
      </div>
    </div>
  );
}

// Export helper to get stored API key
export function getStoredApiKey(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

// Export helper to clear stored API key
export function clearStoredApiKey(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}
