import React, { useEffect, useRef } from 'react';
import { Terminal as TerminalIcon } from 'lucide-react';

interface TerminalViewProps {
  logs: string[];
  currentStep?: string;
  status?: string;
}

export const TerminalView: React.FC<TerminalViewProps> = ({ logs, currentStep, status }) => {
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="terminal-container">
      <div className="terminal-header">
        <div className="flex-row gap-sm">
          <div className="terminal-dots">
            <div className="terminal-dot dot-red"></div>
            <div className="terminal-dot dot-yellow"></div>
            <div className="terminal-dot dot-green"></div>
          </div>
          <span className="flex-row gap-sm" style={{ fontWeight: 600 }}>
            <TerminalIcon size={14} /> SRE Upgrade Console
          </span>
        </div>

        <div className="flex-row gap-sm">
          {currentStep && (
            <span style={{ color: 'var(--accent-emerald)', fontWeight: 600 }}>
              {currentStep}
            </span>
          )}
          {status && (
            <span className={`badge ${status === 'RUNNING' ? 'badge-info' : status === 'SUCCESS' ? 'badge-healthy' : 'badge-warning'}`}>
              {status}
            </span>
          )}
        </div>
      </div>

      <div className="terminal-body">
        {logs.length === 0 ? (
          <div className="text-muted" style={{ fontStyle: 'italic' }}>
            Awaiting upgrade tasks...
          </div>
        ) : (
          logs.map((line, idx) => (
            <div key={idx} className="terminal-line">
              <span className="terminal-prompt">&gt;</span>
              <span>{line}</span>
            </div>
          ))
        )}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
};
