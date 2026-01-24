'use client';

import { FormField, PdfDisplayMode } from '@/types';
import PdfUpload from './PdfUpload';
import FormFields from './FormFields';
import PdfViewer from './PdfViewer';

interface LeftPanelProps {
  file: File | null;
  onFileSelect: (file: File | null) => void;
  onNewSession?: () => void;
  fields: FormField[];
  originalPdfBytes: Uint8Array | null;  // For restored sessions
  filledPdfBytes: Uint8Array | null;
  pdfDisplayMode: PdfDisplayMode;
  onPdfDisplayModeChange: (mode: PdfDisplayMode) => void;
  isAnalyzing: boolean;
  isProcessing: boolean;
}

export default function LeftPanel({
  file,
  onFileSelect,
  onNewSession,
  fields,
  originalPdfBytes,
  filledPdfBytes,
  pdfDisplayMode,
  onPdfDisplayModeChange,
  isAnalyzing,
  isProcessing,
}: LeftPanelProps) {
  const handleReset = () => {
    if (!isProcessing) {
      // If onNewSession is provided, use it for a complete fresh start
      if (onNewSession) {
        onNewSession();
      } else {
        onFileSelect(null);
      }
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between glass">
        <div>
          <h2 className="text-sm font-semibold tracking-wide">表单</h2>
          <p className="text-xs text-foreground-muted">
            {file ? file.name : '上传并预览您的 PDF'}
          </p>
        </div>
        {file && (
          <button
            onClick={handleReset}
            disabled={isProcessing}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-white/5 text-foreground-muted hover:text-foreground-secondary hover:bg-white/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-white/5"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            新表单
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col p-4 gap-4 overflow-hidden">
        {/* Upload section - only show when no file is selected AND no restored PDF bytes */}
        {!file && !originalPdfBytes && !filledPdfBytes && (
          <div className="flex-1 flex items-center justify-center">
            <div className="w-full max-w-md">
              <PdfUpload
                onFileSelect={onFileSelect}
                selectedFile={file}
                disabled={isProcessing}
              />
            </div>
          </div>
        )}

        {/* Loading state */}
        {isAnalyzing && (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex items-center gap-3 text-foreground-muted">
              <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
              <span className="text-sm">正在分析 PDF...</span>
            </div>
          </div>
        )}

        {/* PDF Viewer - takes full space when file is present OR we have restored PDF bytes */}
        {(file || originalPdfBytes || filledPdfBytes) && !isAnalyzing && (
          <PdfViewer
            originalFile={file}
            originalPdfBytes={originalPdfBytes}
            filledPdfBytes={filledPdfBytes}
            mode={pdfDisplayMode}
            onModeChange={onPdfDisplayModeChange}
          />
        )}

        {/* Fields panel - collapsible at bottom */}
        {fields.length > 0 && !isAnalyzing && (
          <details className="flex-shrink-0 border-t border-border pt-3">
            <summary className="cursor-pointer text-sm font-medium text-foreground-secondary hover:text-foreground transition-colors py-1 flex items-center gap-2 select-none">
              <svg className="w-4 h-4 transition-transform [details[open]>&]:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              检测到的字段 ({fields.length})
            </summary>
            <div className="mt-2 max-h-[200px] overflow-y-auto">
              <FormFields fields={fields} />
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
