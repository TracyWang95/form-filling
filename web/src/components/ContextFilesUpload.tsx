'use client';

import { useCallback, useState } from 'react';

export interface ContextFile {
  filename: string;
  content: string;
  was_parsed: boolean;
}

export interface ParseProgress {
  current: number;
  total: number;
  filename: string;
  status: 'parsing' | 'reading_text' | 'openparse' | 'complete' | 'error';
  error?: string;
}

interface ContextFilesUploadProps {
  files: ContextFile[];
  onFilesChange: (files: ContextFile[]) => void;
  onParseFiles: (files: File[], parseMode: 'fast' | 'detailed') => Promise<void>;
  isUploading: boolean;
  parseProgress: ParseProgress | null;
  disabled?: boolean;
  maxFiles?: number;
}

export default function ContextFilesUpload({
  files,
  onFilesChange,
  onParseFiles,
  isUploading,
  parseProgress,
  disabled,
  maxFiles = 5,
}: ContextFilesUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [parseMode, setParseMode] = useState<'fast' | 'detailed'>('fast');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (!disabled && !isUploading) setIsDragging(true);
  }, [disabled, isUploading]);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (disabled || isUploading) return;

    const droppedFiles = Array.from(e.dataTransfer.files);
    const currentCount = files.length + pendingFiles.length;
    const remainingSlots = maxFiles - currentCount;

    if (remainingSlots <= 0) return;

    const newFiles = droppedFiles.slice(0, remainingSlots);
    setPendingFiles(prev => [...prev, ...newFiles]);
  }, [disabled, isUploading, files.length, pendingFiles.length, maxFiles]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.length) return;

    const selectedFiles = Array.from(e.target.files);
    const currentCount = files.length + pendingFiles.length;
    const remainingSlots = maxFiles - currentCount;

    if (remainingSlots <= 0) return;

    const newFiles = selectedFiles.slice(0, remainingSlots);
    setPendingFiles(prev => [...prev, ...newFiles]);

    // Reset the input
    e.target.value = '';
  }, [files.length, pendingFiles.length, maxFiles]);

  const handleRemovePending = useCallback((index: number) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleRemoveUploaded = useCallback((index: number) => {
    onFilesChange(files.filter((_, i) => i !== index));
  }, [files, onFilesChange]);

  const handleUpload = useCallback(async () => {
    if (pendingFiles.length === 0 || isUploading) return;

    await onParseFiles(pendingFiles, parseMode);
    setPendingFiles([]);
  }, [pendingFiles, parseMode, isUploading, onParseFiles]);

  const totalCount = files.length + pendingFiles.length;
  const canAddMore = totalCount < maxFiles;

  return (
    <div className="space-y-3">
      {/* Header with toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="text-xs font-medium text-foreground-secondary">
            上下文文件 ({totalCount}/{maxFiles})
          </span>
        </div>

        {/* Parse mode toggle */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-foreground-muted">模式:</span>
          <select
            value={parseMode}
            onChange={(e) => setParseMode(e.target.value as 'fast' | 'detailed')}
            disabled={disabled || isUploading}
            className="text-xs px-2 py-1 rounded bg-background border border-border text-foreground disabled:opacity-50"
          >
            <option value="fast">快速</option>
            <option value="detailed">详细</option>
          </select>
        </div>
      </div>

      {/* Drop zone - only show if can add more */}
      {canAddMore && (
        <div
          className={`
            relative border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all
            ${isDragging ? 'border-foreground bg-foreground/5' : 'border-border hover:border-foreground/40'}
            ${disabled || isUploading ? 'opacity-50 cursor-not-allowed' : ''}
          `}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !disabled && !isUploading && document.getElementById('context-files-input')?.click()}
        >
          <input
            id="context-files-input"
            type="file"
            multiple
            accept=".pdf,.pptx,.ppt,.docx,.doc,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.txt,.md,.csv,.json,.xml,.html"
            className="hidden"
            onChange={handleFileChange}
            disabled={disabled || isUploading}
          />

          <div className="flex flex-col items-center gap-2">
            <svg className="w-8 h-8 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-xs text-foreground-secondary">
              拖放文件或 <span className="text-foreground font-medium">点击选择</span>
            </p>
            <p className="text-xs text-foreground-muted">
              PDF、PPT、Word、图片或文本文件
            </p>
          </div>
        </div>
      )}

      {/* Pending files list */}
      {pendingFiles.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-foreground-muted">待上传:</p>
          <div className="space-y-1">
            {pendingFiles.map((file, index) => (
              <div
                key={`pending-${index}`}
                className="flex items-center justify-between px-3 py-2 rounded-lg bg-background-tertiary border border-border"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileIcon filename={file.name} />
                  <span className="text-xs text-foreground-secondary truncate">{file.name}</span>
                  <span className="text-xs text-foreground-muted">
                    ({(file.size / 1024).toFixed(1)} KB)
                  </span>
                </div>
                <button
                  onClick={() => handleRemovePending(index)}
                  disabled={isUploading}
                  className="p-1 hover:bg-border rounded transition-colors disabled:opacity-50"
                >
                  <svg className="w-3 h-3 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>

          {/* Upload button */}
          <button
            onClick={handleUpload}
            disabled={isUploading || disabled}
            className="w-full px-4 py-2 rounded-lg bg-foreground text-background text-xs font-medium hover:bg-foreground-secondary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isUploading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-3 h-3 border-2 border-background border-t-transparent rounded-full animate-spin" />
                {parseProgress ? `正在解析 ${parseProgress.filename}...` : '上传中...'}
              </span>
            ) : (
              `上传并解析 ${pendingFiles.length} 个文件`
            )}
          </button>
        </div>
      )}

      {/* Parse progress */}
      {isUploading && parseProgress && (
        <div className="px-3 py-2 rounded-lg bg-foreground/5 text-foreground border border-border">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs">
              {parseProgress.status === 'openparse' ? '使用 OpenParse 解析中' :
               parseProgress.status === 'reading_text' ? '读取文本文件中' :
               parseProgress.status === 'complete' ? '完成' :
               parseProgress.status === 'error' ? '错误' : '处理中'}
            </span>
            <span className="text-xs">{parseProgress.current}/{parseProgress.total}</span>
          </div>
          <div className="w-full h-1 bg-border rounded-full overflow-hidden">
            <div
              className="h-full bg-foreground transition-all duration-300"
              style={{ width: `${(parseProgress.current / parseProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Uploaded files list */}
      {files.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-foreground-muted">已上传:</p>
          {files.map((file, index) => (
            <div
              key={`uploaded-${index}`}
              className="flex items-center justify-between px-3 py-2 rounded-lg bg-success/10 border border-success/20"
            >
              <div className="flex items-center gap-2 min-w-0">
                <svg className="w-4 h-4 text-success flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <span className="text-xs text-foreground-secondary truncate">{file.filename}</span>
                {file.was_parsed && (
                  <span className="text-xs text-foreground-muted">(已解析)</span>
                )}
              </div>
              <button
                onClick={() => handleRemoveUploaded(index)}
                disabled={isUploading}
                className="p-1 hover:bg-border rounded transition-colors disabled:opacity-50"
              >
                <svg className="w-3 h-3 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Helper component for file type icons
function FileIcon({ filename }: { filename: string }) {
  const ext = filename.split('.').pop()?.toLowerCase() || '';

  const isPdf = ext === 'pdf';
  const isDoc = ['doc', 'docx'].includes(ext);
  const isPpt = ['ppt', 'pptx'].includes(ext);
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext);
  const isText = ['txt', 'md', 'csv', 'json', 'xml', 'html'].includes(ext);

  if (isPdf) {
    return <svg className="w-4 h-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
    </svg>;
  }

  if (isDoc) {
    return <svg className="w-4 h-4 text-blue-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
    </svg>;
  }

  if (isPpt) {
    return <svg className="w-4 h-4 text-orange-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
    </svg>;
  }

  if (isImage) {
    return <svg className="w-4 h-4 text-purple-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z" clipRule="evenodd" />
    </svg>;
  }

  if (isText) {
    return <svg className="w-4 h-4 text-gray-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clipRule="evenodd" />
    </svg>;
  }

  return <svg className="w-4 h-4 text-foreground-muted flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
    <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
  </svg>;
}
