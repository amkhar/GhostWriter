'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

// ---------- Types ---------- //
interface StageEvent {
  stage: number;
  name: string;
  status: 'running' | 'complete' | 'error';
  message: string;
  tasks?: TaskData[];
  stats?: Stats;
}

interface AgentEvent {
  task_id: string;
  title?: string;
  status: 'working' | 'done' | 'failed';
  message?: string;
  summary?: string;
  diff?: string;
  test_status?: string;
}

interface TaskData {
  id: string;
  title: string;
  description: string;
  reason: string;
  auto_doable: boolean;
  auto_doable_category?: string;
  classification_reasoning?: string;
}

interface Stats {
  files_analyzed: number;
  api_calls: number;
  lines_changed: number;
}

interface RunRecord {
  id: string;
  started_at: string;
  finished_at?: string;
  status: string;
  dry_run: number;
  stats_json?: string;
}

// ---------- Main Page ---------- //
export default function Home() {
  const [phase, setPhase] = useState<'idle' | 'recording' | 'pipeline' | 'complete'>('idle');
  const [recording, setRecording] = useState({ lines: [] as string[], partial: '', elapsed: 0 });
  const [stages, setStages] = useState<StageEvent[]>([]);
  const [agents, setAgents] = useState<Record<string, AgentEvent>>({});
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [stats, setStats] = useState<Stats>({ files_analyzed: 0, api_calls: 0, lines_changed: 0 });
  const [report, setReport] = useState('');
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [error, setError] = useState('');
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Load past runs
  useEffect(() => {
    fetch('/api/pipeline/runs').then(r => r.json()).then(setRuns).catch(() => {});
  }, [phase]);

  // Poll recording status
  useEffect(() => {
    if (phase === 'recording') {
      pollRef.current = setInterval(async () => {
        const r = await fetch('/api/recording/status');
        const data = await r.json();
        setRecording({ lines: data.lines, partial: data.partial, elapsed: data.elapsed });
      }, 500);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [phase]);

  const startRecording = async () => {
    setError('');
    try {
      await fetch('/api/recording/start', { method: 'POST' });
      setPhase('recording');
    } catch (e: any) {
      setError(e.message || 'Failed to start recording');
    }
  };

  const stopRecording = async () => {
    const r = await fetch('/api/recording/stop', { method: 'POST' });
    const data = await r.json();
    setPhase('pipeline');
    runPipeline(data.transcript);
  };

  const runPipeline = useCallback((transcript: string) => {
    setStages([]);
    setAgents({});
    setTasks([]);
    setStats({ files_analyzed: 0, api_calls: 0, lines_changed: 0 });
    setReport('');

    const es = new EventSource(`/api/pipeline/run?transcript=${encodeURIComponent(transcript)}&dry_run=false`);

    // SSE via POST isn't standard EventSource — use fetch instead
    fetch('/api/pipeline/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, dry_run: false }),
    }).then(async (response) => {
      const reader = response.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              handleSSEData(line.replace(/^.*?event: /, ''), data);
            } catch {}
          }
          if (line.startsWith('event: ')) {
            const eventType = line.slice(7).trim();
            const nextDataLine = lines[lines.indexOf(line) + 1];
            if (nextDataLine?.startsWith('data: ')) {
              try {
                handleSSEData(eventType, JSON.parse(nextDataLine.slice(6)));
              } catch {}
            }
          }
        }
      }
      setPhase('complete');
    }).catch(e => setError(e.message));

    es.close(); // We don't actually use EventSource for POST
  }, []);

  const handleSSEData = (eventType: string, data: any) => {
    if (data.stats) setStats(data.stats);
    if (data.tasks) setTasks(data.tasks);

    if (eventType === 'stage' || data.stage !== undefined) {
      setStages(prev => {
        const existing = prev.findIndex(s => s.stage === data.stage);
        if (existing >= 0) {
          const updated = [...prev];
          updated[existing] = data;
          return updated;
        }
        return [...prev, data];
      });
    }
    if (eventType === 'agent' || data.task_id) {
      setAgents(prev => ({ ...prev, [data.task_id]: data }));
    }
    if (eventType === 'complete' || data.report) {
      if (data.report) setReport(data.report);
      setPhase('complete');
    }
    if (eventType === 'error') {
      setError(data.message);
    }
  };

  // Actually parse SSE properly
  const runPipelineSSE = useCallback((transcript: string) => {
    setStages([]);
    setAgents({});
    setTasks([]);
    setStats({ files_analyzed: 0, api_calls: 0, lines_changed: 0 });
    setReport('');
    setPhase('pipeline');

    fetch('/api/pipeline/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify({ transcript, dry_run: false }),
    }).then(async (response) => {
      const reader = response.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE format: "event: type\ndata: json\n\n"
        const messages = buffer.split('\n\n');
        buffer = messages.pop() || '';

        for (const msg of messages) {
          let eventType = 'message';
          let eventData = '';
          for (const line of msg.split('\n')) {
            if (line.startsWith('event:')) eventType = line.slice(6).trim();
            if (line.startsWith('data:')) eventData = line.slice(5).trim();
          }
          if (!eventData) continue;
          try {
            const parsed = JSON.parse(eventData);
            if (parsed.stats) setStats(parsed.stats);
            if (parsed.tasks) setTasks(parsed.tasks);

            if (eventType === 'stage') {
              setStages(prev => {
                const idx = prev.findIndex(s => s.stage === parsed.stage);
                if (idx >= 0) { const u = [...prev]; u[idx] = parsed; return u; }
                return [...prev, parsed];
              });
            } else if (eventType === 'agent') {
              setAgents(prev => ({ ...prev, [parsed.task_id]: parsed }));
            } else if (eventType === 'complete') {
              if (parsed.report) setReport(parsed.report);
              if (parsed.tasks) setTasks(parsed.tasks);
              setPhase('complete');
            } else if (eventType === 'error') {
              setError(parsed.message);
              setPhase('complete');
            }
          } catch {}
        }
      }
      if (phase !== 'complete') setPhase('complete');
    }).catch(e => { setError(e.message); setPhase('complete'); });
  }, []);

  const reset = () => {
    setPhase('idle');
    setStages([]);
    setAgents({});
    setTasks([]);
    setReport('');
    setError('');
    setStats({ files_analyzed: 0, api_calls: 0, lines_changed: 0 });
  };

  return (
    <div className="max-w-5xl mx-auto px-6 py-10">
      {/* Header */}
      <header className="text-center mb-12">
        <h1 className="text-4xl font-bold text-gray-900 flex items-center justify-center gap-3">
          <span className="text-5xl">👻</span> GhostWriter
        </h1>
        <p className="text-gray-500 mt-2">Turn standups into shipped code</p>
      </header>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          {error}
          <button onClick={() => setError('')} className="ml-3 underline">dismiss</button>
        </div>
      )}

      {/* Recording Section */}
      {phase === 'idle' && <IdleView onStart={startRecording} onRunWithText={runPipelineSSE} />}
      {phase === 'recording' && <RecordingView recording={recording} onStop={stopRecording} />}

      {/* Pipeline Progress */}
      {(phase === 'pipeline' || phase === 'complete') && (
        <PipelineView stages={stages} agents={agents} tasks={tasks} stats={stats} report={report} complete={phase === 'complete'} onReset={reset} />
      )}

      {/* Past Runs */}
      {runs.length > 0 && <RunHistory runs={runs} />}
    </div>
  );
}

// ---------- Idle View ---------- //
function IdleView({ onStart, onRunWithText }: { onStart: () => void; onRunWithText: (t: string) => void }) {
  const [showText, setShowText] = useState(false);
  const [text, setText] = useState('');

  return (
    <div className="text-center space-y-6">
      <button onClick={onStart}
        className="group relative inline-flex items-center justify-center w-40 h-40 rounded-full bg-primary text-white shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 hover:scale-105 transition-all duration-300">
        <svg className="w-16 h-16" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
          <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
        </svg>
        <span className="absolute -bottom-10 text-gray-700 font-medium text-lg group-hover:text-primary transition-colors">
          Start Standup
        </span>
      </button>

      <div className="pt-8">
        <button onClick={() => setShowText(!showText)} className="text-sm text-gray-400 hover:text-primary transition-colors">
          or paste a transcript manually
        </button>
        {showText && (
          <div className="mt-4 max-w-lg mx-auto space-y-3">
            <textarea value={text} onChange={e => setText(e.target.value)} rows={6} placeholder="Paste your standup transcript here..."
              className="w-full p-4 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none resize-none" />
            <button onClick={() => text.trim() && onRunWithText(text)} disabled={!text.trim()}
              className="px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-blue-700 transition-colors">
              Run Pipeline
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- Recording View ---------- //
function RecordingView({ recording, onStop }: { recording: { lines: string[]; partial: string; elapsed: number }; onStop: () => void }) {
  const mins = Math.floor(recording.elapsed / 60);
  const secs = recording.elapsed % 60;

  return (
    <div className="space-y-6">
      {/* Waveform + Timer */}
      <div className="text-center space-y-4">
        <div className="flex items-center justify-center gap-1 h-16">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="waveform-bar w-1.5 bg-red-500 rounded-full" style={{ height: '100%' }} />
          ))}
        </div>
        <div className="flex items-center justify-center gap-3">
          <span className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
          <span className="text-2xl font-mono font-bold text-gray-800">
            {String(mins).padStart(2, '0')}:{String(secs).padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Live Transcript */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm max-h-64 overflow-y-auto">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Live Transcript</h3>
        {recording.lines.length === 0 && !recording.partial && (
          <p className="text-gray-400 italic">Listening...</p>
        )}
        {recording.lines.map((line, i) => (
          <p key={i} className="text-sm text-gray-700 mb-1">{line}</p>
        ))}
        {recording.partial && <p className="text-sm text-gray-400 italic">{recording.partial}</p>}
      </div>

      {/* Stop Button */}
      <div className="text-center">
        <button onClick={onStop}
          className="px-8 py-3 bg-red-500 text-white rounded-xl font-medium hover:bg-red-600 transition-colors shadow-lg shadow-red-500/20">
          Stop Recording & Run Pipeline
        </button>
      </div>
    </div>
  );
}

// ---------- Pipeline View ---------- //
function PipelineView({ stages, agents, tasks, stats, report, complete, onReset }: {
  stages: StageEvent[]; agents: Record<string, AgentEvent>; tasks: TaskData[]; stats: Stats; report: string; complete: boolean; onReset: () => void;
}) {
  const stageConfig = [
    { num: 1, name: 'Ingest', icon: '📤', desc: 'Uploading transcripts' },
    { num: 2, name: 'Extract', icon: '🧠', desc: 'AI extracting tasks' },
    { num: 3, name: 'Recurrence', icon: '🔗', desc: 'Finding neglected patterns' },
    { num: 4, name: 'Classify', icon: '🏷️', desc: 'Safety classification' },
    { num: 5, name: 'Implement', icon: '⚡', desc: 'Agents coding' },
    { num: 7, name: 'Report', icon: '📋', desc: 'Final summary' },
  ];

  return (
    <div className="space-y-8">
      {/* Stats Bar */}
      <div className="flex justify-center gap-8">
        <StatBadge label="Files Analyzed" value={stats.files_analyzed} />
        <StatBadge label="API Calls" value={stats.api_calls} />
        <StatBadge label="Lines Changed" value={stats.lines_changed} />
      </div>

      {/* Stage Cards */}
      <div className="grid gap-3">
        {stageConfig.map(cfg => {
          const stage = stages.find(s => s.stage === cfg.num);
          const status = stage?.status || 'pending';
          return (
            <div key={cfg.num} className={`flex items-center gap-4 p-4 rounded-xl border transition-all duration-500 ${
              status === 'complete' ? 'bg-green-50 border-green-200' :
              status === 'running' ? 'bg-blue-50 border-blue-200 shadow-md' :
              'bg-white border-gray-100'
            }`}>
              <span className="text-2xl">{cfg.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-gray-800">Stage {cfg.num}: {cfg.name}</span>
                  {status === 'running' && <Spinner />}
                  {status === 'complete' && <span className="text-success text-lg">✓</span>}
                </div>
                <p className="text-xs text-gray-500 truncate">{stage?.message || cfg.desc}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Agent Cards */}
      {Object.keys(agents).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Agent Activity</h3>
          {Object.values(agents).map(agent => (
            <div key={agent.task_id} className={`p-4 rounded-xl border ${
              agent.status === 'working' ? 'bg-amber-50 border-amber-200' :
              agent.status === 'done' ? 'bg-green-50 border-green-200' :
              'bg-red-50 border-red-200'
            }`}>
              <div className="flex items-center gap-2 mb-1">
                {agent.status === 'working' && <Spinner />}
                {agent.status === 'done' && <span className="text-success">✓</span>}
                {agent.status === 'failed' && <span className="text-error">✗</span>}
                <span className="font-medium text-sm">{agent.title || agent.task_id}</span>
              </div>
              {agent.message && <p className="text-xs text-gray-500">{agent.message}</p>}
              {agent.summary && <p className="text-xs text-gray-600 mt-1">{agent.summary}</p>}
              {agent.diff && (
                <pre className="mt-2 text-xs bg-gray-900 text-green-400 p-3 rounded-lg overflow-x-auto max-h-32 overflow-y-auto">
                  {agent.diff.slice(0, 500)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Task Cards */}
      {tasks.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Tasks</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {tasks.map(task => (
              <div key={task.id} className="p-4 bg-white rounded-xl border border-gray-200 shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-medium text-sm text-gray-800">{task.title}</h4>
                  <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-medium ${
                    task.auto_doable ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                  }`}>
                    {task.auto_doable ? '✓ Auto' : '✗ Skip'}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-1 line-clamp-2">{task.description}</p>
                {task.classification_reasoning && (
                  <p className="text-xs text-gray-400 mt-1 italic">{task.classification_reasoning}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Complete */}
      {complete && (
        <div className="text-center pt-4 space-y-4">
          {report && (
            <details className="text-left bg-white rounded-xl border border-gray-200 p-4">
              <summary className="cursor-pointer font-medium text-sm text-gray-700">View Full Report</summary>
              <pre className="mt-3 text-xs text-gray-600 whitespace-pre-wrap">{report}</pre>
            </details>
          )}
          <button onClick={onReset} className="px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
            New Run
          </button>
        </div>
      )}
    </div>
  );
}

// ---------- Run History ---------- //
function RunHistory({ runs }: { runs: RunRecord[] }) {
  return (
    <div className="mt-16 pt-8 border-t border-gray-200">
      <h2 className="text-lg font-semibold text-gray-800 mb-4">Past Runs</h2>
      <div className="space-y-2">
        {runs.map(run => {
          const stats = run.stats_json ? JSON.parse(run.stats_json) : null;
          return (
            <div key={run.id} className="flex items-center gap-4 p-3 bg-white rounded-lg border border-gray-100">
              <span className={`w-2 h-2 rounded-full ${
                run.status === 'complete' ? 'bg-success' : run.status === 'failed' ? 'bg-error' : 'bg-warning animate-pulse'
              }`} />
              <span className="font-mono text-xs text-gray-500">{run.id}</span>
              <span className="text-xs text-gray-400">{new Date(run.started_at).toLocaleString()}</span>
              {run.dry_run ? <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">dry-run</span> : null}
              {stats && <span className="text-xs text-gray-400 ml-auto">{stats.api_calls} API calls</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- Helpers ---------- //
function Spinner() {
  return <span className="inline-block w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />;
}

function StatBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="text-2xl font-bold text-primary">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}
