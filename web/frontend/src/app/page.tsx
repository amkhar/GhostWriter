'use client';

import { useState, useEffect, useRef } from 'react';

type View = 'home' | 'running' | 'detail';
type TaskItem = { id: string; title: string; description: string; reason: string; auto_doable: boolean; auto_doable_category?: string; classification_reasoning?: string };
type AgentResult = { task_id: string; status: string; summary?: string; diff?: string; test_status?: string; title?: string; message?: string; branch?: string; error?: string };
type StageInfo = { stage: number; name: string; status: string; message: string; stats?: any; tasks?: TaskItem[] };
type RecStatus = { active: boolean; lines: string[]; partial: string; elapsed: number };
type LogEntry = { time: string; source: string; msg: string; type: 'info' | 'success' | 'warning' | 'error' };

export default function Home() {
  const [view, setView] = useState<View>('home');
  const [recording, setRecording] = useState(false);
  const [recStatus, setRecStatus] = useState<RecStatus>({ active: false, lines: [], partial: '', elapsed: 0 });
  const [stages, setStages] = useState<StageInfo[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [agents, setAgents] = useState<AgentResult[]>([]);
  const [stats, setStats] = useState<any>({});
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedRun, setSelectedRun] = useState<any>(null);
  const [pipelineActive, setPipelineActive] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [copiedTaskDiff, setCopiedTaskDiff] = useState<string | null>(null);
  const [expandedDiffs, setExpandedDiffs] = useState<Record<string, boolean>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [guidanceInputs, setGuidanceInputs] = useState<Record<string, string>>({});

  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (recording) {
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetch('/api/recording/status');
          if (r.ok) setRecStatus(await r.json());
        } catch {}
      }, 400);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [recording]);

  useEffect(() => {
    loadRuns();
  }, []);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const loadRuns = () => fetch('/api/pipeline/runs').then(r => r.json()).then(setRuns).catch(() => {});

  const addLog = (source: string, msg: string, type: 'info' | 'success' | 'warning' | 'error' = 'info') => {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setLogs(prev => [...prev, { time, source, msg, type }]);
  };

  const startRec = async () => {
    const res = await fetch('/api/recording/start', { method: 'POST' });
    if (res.ok) setRecording(true);
  };

  const stopRec = async () => {
    const res = await fetch('/api/recording/stop', { method: 'POST' });
    if (!res.ok) return;
    const data = await res.json();
    setRecording(false);
    startPipeline(data.transcript);
  };

  const startPipeline = (transcript: string) => {
    setView('running');
    setPipelineActive(true);
    setStages([]);
    setTasks([]);
    setAgents([]);
    setStats({});
    setLogs([]);
    setSelectedTask(null);
    setExpandedDiffs({});
    setRunId(null);
    setGuidanceInputs({});

    addLog('System', 'Initializing GhostWriter backend pipeline...', 'info');

    const url = `/api/pipeline/stream?transcript=${encodeURIComponent(transcript)}&repo=${encodeURIComponent('/Users/himmi/casacadia/GhostWriter')}`;
    const es = new EventSource(url);

    es.addEventListener('stage', (e) => {
      const d = JSON.parse(e.data);
      setStages(prev => {
        const i = prev.findIndex(s => s.stage === d.stage);
        if (i >= 0) {
          const n = [...prev];
          n[i] = d;
          return n;
        }
        return [...prev, d];
      });

      if (d.run_id) {
        setRunId(d.run_id);
      }

      if (d.status === 'running') {
        addLog(d.name, d.message, 'info');
      } else if (d.status === 'complete') {
        addLog(d.name, d.message, 'success');
      }

      if (d.tasks) {
        setTasks(d.tasks);
        if (d.stage === 3) {
          addLog('Recurrence', `Found ${d.tasks.length} recurring neglected task(s).`, 'info');
        } else if (d.stage === 4) {
          const safeCount = d.tasks.filter((t: any) => t.auto_doable).length;
          addLog('Classifier', `Classification complete. ${safeCount} of ${d.tasks.length} tasks marked auto-doable.`, 'success');
        }
      }
      if (d.stats) setStats(d.stats);
    });

    es.addEventListener('agent', (e) => {
      const d = JSON.parse(e.data);
      setAgents(prev => {
        const i = prev.findIndex(a => a.task_id === d.task_id);
        if (i >= 0) {
          const n = [...prev];
          n[i] = { ...n[i], ...d };
          return n;
        }
        return [...prev, d];
      });

      let logType: 'info' | 'success' | 'error' = 'info';
      if (d.status === 'done') logType = 'success';
      else if (d.status === 'failed') logType = 'error';

      addLog(`Agent:${d.title || d.task_id.substring(0, 15)}`, d.message || `Status changed to: ${d.status}`, logType);
    });

    es.addEventListener('complete', (e) => {
      const d = JSON.parse(e.data);
      if (d.tasks) setTasks(d.tasks);
      if (d.stats) setStats(d.stats);
      if (d.run_id) setRunId(d.run_id);
      addLog('System', 'Pipeline execution complete. All tasks finalized.', 'success');
      setPipelineActive(false);
      es.close();
      loadRuns();
    });

    es.addEventListener('error', (e: any) => {
      const msg = e.data ? JSON.parse(e.data).message : 'Connection closed';
      addLog('System', `Pipeline encountered an error: ${msg}`, 'error');
      setPipelineActive(false);
      es.close();
    });

    es.onerror = () => {
      addLog('System', 'Pipeline connection disrupted.', 'error');
      setPipelineActive(false);
      es.close();
    };
  };

  const fmt = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

  const loadRunDetail = async (id: string) => {
    const res = await fetch(`/api/pipeline/runs/${id}`);
    if (res.ok) {
      const runData = await res.json();
      setSelectedRun(runData);
      setRunId(id);
      setView('detail');
    }
  };

  const toggleDiff = (taskId: string) => {
    setExpandedDiffs(prev => ({ ...prev, [taskId]: !prev[taskId] }));
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedTaskDiff(id);
    setTimeout(() => setCopiedTaskDiff(null), 2000);
  };

  const handleOverride = (taskId: string, guidance: string) => {
    if (!runId) {
      addLog('System', 'Run ID not found. Overrides require an active or historical run context.', 'error');
      return;
    }

    // 1. Move task locally to auto doable
    setTasks(prev =>
      prev.map(t =>
        t.id === taskId
          ? {
              ...t,
              auto_doable: true,
              auto_doable_category: 'user-directed',
              classification_reasoning: `User override: ${guidance}`,
            }
          : t
      )
    );

    // 2. Set agents loading
    setAgents(prev => {
      const exists = prev.some(a => a.task_id === taskId);
      if (exists) {
        return prev.map(a =>
          a.task_id === taskId
            ? {
                ...a,
                status: 'working',
                message: 'Initializing custom workspace...',
                branch: `ghostwriter/${taskId.substring(0, 30)}`,
                error: undefined,
                diff: undefined,
                summary: undefined,
                test_status: undefined,
              }
            : a
        );
      }
      return [
        ...prev,
        {
          task_id: taskId,
          status: 'working',
          message: 'Initializing custom workspace...',
          branch: `ghostwriter/${taskId.substring(0, 30)}`,
        },
      ];
    });

    addLog(`Override:${taskId.substring(0, 15)}`, `User override submitted. Initializing custom workspace...`, 'info');

    // 3. Trigger override pipeline
    const url = `/api/tasks/${encodeURIComponent(taskId)}/override?run_id=${encodeURIComponent(runId)}&guidance=${encodeURIComponent(guidance)}`;
    const es = new EventSource(url);

    es.addEventListener('agent', (e) => {
      const d = JSON.parse(e.data);
      setAgents(prev => {
        const i = prev.findIndex(a => a.task_id === d.task_id);
        if (i >= 0) {
          const n = [...prev];
          n[i] = { ...n[i], ...d };
          return n;
        }
        return [...prev, d];
      });

      let logType: 'info' | 'success' | 'error' = 'info';
      if (d.status === 'done') logType = 'success';
      else if (d.status === 'failed') logType = 'error';

      addLog(`Agent:${d.title || d.task_id.substring(0, 15)}`, d.message || `Status changed to: ${d.status}`, logType);
    });

    es.addEventListener('complete', () => {
      addLog(`Override:${taskId.substring(0, 15)}`, `Override implementation completed successfully.`, 'success');
      es.close();
      loadRuns();
    });

    es.addEventListener('error', () => {
      addLog(`Override:${taskId.substring(0, 15)}`, `Override connection lost or failed.`, 'error');
      es.close();
    });
  };

  // ─── HOME VIEW ───
  if (view === 'home' && !recording) {
    return (
      <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col">
        <Nav />
        <div className="flex-1 flex flex-col items-center justify-center px-6 max-w-4xl mx-auto w-full py-12">
          <div className="text-center mb-12">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold uppercase tracking-wider mb-4 animate-pulse">
              Agentic Automation Engine
            </div>
            <h1 className="text-5xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              Turn standups into shipped code
            </h1>
            <p className="mt-4 text-lg text-slate-400 max-w-2xl mx-auto">
              GhostWriter listens to your team's standup, automatically extracts recurring neglected tasks, researches the codebase for safety, and implements safe fixes in parallel.
            </p>
          </div>

          <div className="relative group">
            <div className="absolute -inset-0.5 bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full blur opacity-50 group-hover:opacity-75 transition duration-1000 group-hover:duration-200 animate-tilt"></div>
            <button
              onClick={startRec}
              className="relative w-28 h-28 rounded-full bg-slate-900 border border-slate-800 hover:border-slate-700 transition-all flex items-center justify-center shadow-2xl hover:scale-105"
            >
              <svg className="w-10 h-10 text-blue-400 group-hover:text-blue-300 transition-colors animate-pulse" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
              </svg>
            </button>
          </div>
          <p className="mt-4 text-sm text-slate-500 font-medium tracking-wide">CLICK MICROPHONE TO START STANDUP RECORDING</p>

          {runs.length > 0 && (
            <div className="mt-16 w-full glass-panel rounded-2xl p-6 border border-slate-800">
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4">Pipeline Execution History</h2>
              <div className="divide-y divide-slate-800/60">
                {runs.slice(0, 5).map((r: any) => (
                  <div
                    key={r.id}
                    onClick={() => loadRunDetail(r.id)}
                    className="flex items-center justify-between py-3.5 hover:bg-slate-800/30 px-3 -mx-3 rounded-lg cursor-pointer transition-all duration-200"
                  >
                    <div className="flex items-center gap-3">
                      <span className={`w-2.5 h-2.5 rounded-full ${r.status === 'complete' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : r.status === 'failed' ? 'bg-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]' : 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]'}`} />
                      <span className="text-sm font-medium text-slate-300 truncate max-w-md">{r.transcript_preview || `Run ${r.id}`}</span>
                    </div>
                    <div className="flex items-center gap-6 text-xs text-slate-500">
                      {r.stats?.api_calls && (
                        <span className="bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/50">
                          {r.stats.api_calls} calls
                        </span>
                      )}
                      <span>{new Date(r.started_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ─── RECORDING VIEW ───
  if (recording) {
    return (
      <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col">
        <Nav />
        <div className="flex-1 flex flex-col items-center justify-center px-6 max-w-3xl mx-auto w-full py-12">
          <div className="flex flex-col items-center gap-4 mb-8 text-center">
            <div className="flex items-center gap-3 bg-rose-500/10 border border-rose-500/20 px-4 py-2 rounded-full">
              <span className="w-3.5 h-3.5 bg-rose-500 rounded-full animate-ping" />
              <span className="text-sm font-bold uppercase tracking-widest text-rose-400">Live Recording</span>
              <span className="text-sm text-rose-300 font-mono font-bold ml-2">{fmt(recStatus.elapsed)}</span>
            </div>
            <p className="text-slate-400 text-sm">Speak clearly. We are transcribing and analyzing meeting details in real-time.</p>
          </div>

          <div className="w-full bg-[#0d1222] border border-slate-800 rounded-2xl p-6 min-h-[350px] max-h-[450px] overflow-y-auto shadow-2xl flex flex-col justify-between">
            <div className="space-y-3">
              {recStatus.lines.length === 0 && !recStatus.partial && (
                <div className="flex items-center gap-2 text-slate-600 italic text-sm">
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Listening to micro audio stream...
                </div>
              )}
              {recStatus.lines.map((l, i) => (
                <p key={i} className="text-sm text-slate-300 leading-relaxed bg-slate-900/50 p-3 rounded-lg border border-slate-800/30">
                  {l}
                </p>
              ))}
              {recStatus.partial && (
                <p className="text-sm text-blue-400/80 italic p-3 border border-dashed border-blue-500/10 bg-blue-500/5 rounded-lg">
                  {recStatus.partial}
                  <span className="animate-blink font-bold ml-0.5">|</span>
                </p>
              )}
            </div>
          </div>

          <button
            onClick={stopRec}
            className="mt-8 px-8 py-3.5 bg-gradient-to-r from-rose-600 to-rose-700 hover:from-rose-500 hover:to-rose-600 text-white font-bold text-sm tracking-widest uppercase rounded-xl transition-all shadow-lg hover:shadow-rose-950/20 active:scale-95"
          >
            Stop and Process
          </button>
        </div>
      </div>
    );
  }

  // ─── RUNNING / RESULTS VIEW ───
  if (view === 'running') {
    const working = agents.filter(a => a.status === 'working');
    const done = agents.filter(a => a.status === 'done');
    const failed = agents.filter(a => a.status === 'failed');
    const queued = agents.filter(a => a.status === 'queued');

    const autoTasks = tasks.filter(t => t.auto_doable);
    const skippedTasks = tasks.filter(t => !t.auto_doable);

    // Determine currently active stage index
    const activeStage = stages.find(s => s.status === 'running')?.stage ?? 
                       (pipelineActive ? (stages[stages.length - 1]?.stage ?? 0) : 7);

    return (
      <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col">
        <Nav onBack={() => { setView('home'); loadRuns(); }} />

        {/* Visual Stage Progress Tracker */}
        <div className="bg-[#111827]/80 border-b border-slate-800/80 px-6 py-4 backdrop-blur-md">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
              <div className="flex items-center gap-4">
                <h2 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                  {pipelineActive ? (
                    <>
                      <span className="w-2.5 h-2.5 bg-blue-500 rounded-full animate-ping" />
                      <span>Pipeline Live Executing</span>
                    </>
                  ) : (
                    <>
                      <span className="w-2.5 h-2.5 bg-emerald-500 rounded-full" />
                      <span className="text-emerald-400">Execution Finalized</span>
                    </>
                  )}
                </h2>
                <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-800 px-3 py-1 rounded-full border border-slate-700/50">
                  <span className="text-slate-200 font-bold">{tasks.length}</span> neglected task(s) detected
                </div>
              </div>

              {stats && (
                <div className="flex gap-4 text-xs font-mono text-slate-400 bg-slate-900/60 p-2 rounded-lg border border-slate-800/60">
                  <div>Files Analyzed: <span className="text-blue-400 font-bold">{stats.files_analyzed || 0}</span></div>
                  <div className="border-l border-slate-800 pl-4">API Calls: <span className="text-indigo-400 font-bold">{stats.api_calls || 0}</span></div>
                  <div className="border-l border-slate-800 pl-4">Lines Changed: <span className="text-emerald-400 font-bold">{stats.lines_changed || 0}</span></div>
                </div>
              )}
            </div>

            {/* Horizontal Stage Timeline */}
            <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-2 pt-2">
              {[
                { s: 1, label: 'Ingest', desc: 'Transcript Upload' },
                { s: 2, label: 'Extract', desc: 'Box AI extraction' },
                { s: 3, label: 'Recurrence', desc: 'Neglected Analysis' },
                { s: 4, label: 'Classify', desc: 'Bedrock Safety Classify' },
                { s: 5, label: 'Implement', desc: 'Parallel Coding' },
                { s: 7, label: 'Report', desc: 'Generate Report' },
              ].map((stageItem) => {
                const stageData = stages.find(st => st.stage === stageItem.s);
                const isCompleted = stageData?.status === 'complete' || activeStage > stageItem.s;
                const isRunning = stageData?.status === 'running' || (pipelineActive && activeStage === stageItem.s);
                const statusColor = isCompleted ? 'border-emerald-500/40 bg-emerald-950/20 text-emerald-400' :
                                    isRunning ? 'border-blue-500 bg-blue-950/30 text-blue-400 animate-glow-blue' :
                                    'border-slate-800/80 bg-slate-900/40 text-slate-500';
                return (
                  <div key={stageItem.s} className={`p-2.5 rounded-xl border ${statusColor} transition-all duration-300 flex flex-col justify-between min-h-[64px]`}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold uppercase tracking-wider">{stageItem.label}</span>
                      {isCompleted ? (
                        <span className="w-2 h-2 bg-emerald-500 rounded-full" />
                      ) : isRunning ? (
                        <span className="w-2 h-2 bg-blue-400 rounded-full animate-ping" />
                      ) : (
                        <span className="w-2 h-2 bg-slate-700 rounded-full" />
                      )}
                    </div>
                    <span className="text-[10px] text-slate-400 mt-1 truncate">{stageData?.message || stageItem.desc}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col lg:flex-row max-w-7xl mx-auto w-full p-6 gap-6 overflow-hidden">
          {/* Left panel: Live Console & Discovered Tasks */}
          <div className="w-full lg:w-96 flex flex-col gap-6 flex-shrink-0">
            {/* Live Terminal Console */}
            <div className="glass-panel rounded-2xl flex flex-col shadow-xl overflow-hidden h-72 border border-slate-800">
              <div className="bg-[#111827]/90 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                  </span>
                  <span className="text-xs font-mono font-semibold text-slate-400 ml-2">Console Live Activity</span>
                </div>
                <button
                  onClick={() => setLogs([])}
                  className="text-slate-500 hover:text-slate-300 text-xs font-mono"
                  title="Clear Console Logs"
                >
                  Clear
                </button>
              </div>
              <div className="flex-1 bg-[#090d16] p-4 font-mono text-[11px] overflow-y-auto leading-relaxed space-y-1">
                {logs.length === 0 && (
                  <div className="text-slate-600 italic">Console initialized. Awaiting active streams...</div>
                )}
                {logs.map((log, index) => {
                  const color = log.type === 'success' ? 'text-emerald-400' :
                                log.type === 'warning' ? 'text-amber-400' :
                                log.type === 'error' ? 'text-rose-400' : 'text-slate-300';
                  return (
                    <div key={index} className="flex items-start gap-1">
                      <span className="text-slate-600 font-bold select-none">{log.time}</span>
                      <span className="text-indigo-400 font-bold select-none">[{log.source}]</span>
                      <span className={`${color} break-all`}>{log.msg}</span>
                    </div>
                  );
                })}
                <div ref={terminalEndRef} />
              </div>
            </div>

            {/* Discovered Tasks List */}
            <div className="glass-panel rounded-2xl p-5 flex flex-col flex-1 shadow-xl min-h-[250px] border border-slate-800 overflow-y-auto">
              <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Discovered Tasks ({tasks.length})</h3>
              {tasks.length === 0 && (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
                  <svg className="w-8 h-8 animate-spin text-slate-600 mb-2" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <p className="text-xs text-slate-500 italic">Analyzing transcripts. Discovered tasks will populate immediately.</p>
                </div>
              )}
              <div className="space-y-2">
                {tasks.map(t => {
                  const isSelected = selectedTask === t.id;
                  const agentResult = agents.find(a => a.task_id === t.id);
                  const isSafe = t.auto_doable;
                  const statusTag = !stageChecked(stages, 4) ? 'Classifying' :
                                    isSafe ? 'Safe to Auto-Implement' : 'Manual Review Required';
                  const tagColor = !stageChecked(stages, 4) ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                                   isSafe ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                                   'bg-amber-500/10 text-amber-400 border-amber-500/20';

                  return (
                    <div
                      key={t.id}
                      onClick={() => setSelectedTask(isSelected ? null : t.id)}
                      className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 hover:bg-slate-800/30 ${isSelected ? 'bg-slate-800/50 border-blue-500' : 'bg-slate-900/30 border-slate-800/80'}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-semibold text-xs text-slate-200 truncate max-w-[180px]">{t.title}</div>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded border font-semibold ${tagColor}`}>
                          {statusTag}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1 line-clamp-2">{t.description}</p>
                      {agentResult && (
                        <div className="mt-2 flex items-center gap-1.5 text-[9px] font-mono text-slate-500">
                          <span className={`w-1.5 h-1.5 rounded-full ${agentResult.status === 'done' ? 'bg-emerald-500' : agentResult.status === 'failed' ? 'bg-rose-500' : 'bg-blue-500 animate-pulse'}`} />
                          <span>Agent Status: <strong className="text-slate-400">{agentResult.status}</strong></span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Right panel: Workspaces & Skipped manual tasks */}
          <div className="flex-1 bg-slate-900/10 rounded-2xl overflow-y-auto">
            {selectedTask && tasks.find(t => t.id === selectedTask) ? (
              <div className="glass-panel rounded-2xl p-6 shadow-xl border border-slate-800">
                <div className="flex items-center justify-between border-b border-slate-850 pb-4 mb-4">
                  <h3 className="text-lg font-bold text-white">{tasks.find(t => t.id === selectedTask)?.title}</h3>
                  <button onClick={() => setSelectedTask(null)} className="text-slate-500 hover:text-slate-300 font-mono text-xs">
                    Close Details
                  </button>
                </div>
                <TaskDetail
                  task={tasks.find(t => t.id === selectedTask)!}
                  agent={agents.find(a => a.task_id === selectedTask)}
                  expandedDiffs={expandedDiffs}
                  toggleDiff={toggleDiff}
                  copyToClipboard={copyToClipboard}
                  copiedTaskDiff={copiedTaskDiff}
                />
              </div>
            ) : (
              <div className="h-full flex flex-col space-y-6">
                {/* 1. Safe Workspaces (ThreadPool implementations) */}
                <div>
                  <div className="mb-3">
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
                      Active Auto-Coding Workspaces ({autoTasks.length})
                    </h3>
                    <p className="text-[11px] text-slate-500 mt-0.5">Safe, localized tasks being implemented in parallel sandbox workspaces.</p>
                  </div>

                  {autoTasks.length === 0 && (
                    <div className="p-8 text-center glass-panel border border-slate-850 rounded-2xl">
                      {pipelineActive && !stageChecked(stages, 4) ? (
                        <div className="flex flex-col items-center justify-center py-4">
                          <svg className="w-8 h-8 animate-spin text-blue-500 mb-2" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                          <p className="text-xs text-slate-400 font-semibold">Running Safety Classification...</p>
                          <p className="text-[10px] text-slate-500 mt-0.5">Analyzing codebase and assessing safe vs risky tasks.</p>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 italic py-4">No tasks classified as auto-implementable in this run.</p>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {autoTasks.map(t => {
                      const a = agents.find(agentItem => agentItem.task_id === t.id) || {
                        task_id: t.id,
                        title: t.title,
                        status: 'queued',
                        message: 'Queued for implementation pool',
                      };
                      const isExpanded = expandedDiffs[a.task_id] || false;
                      const diffLinesCount = a.diff ? a.diff.split('\n').length : 0;
                      return (
                        <div
                          key={a.task_id}
                          className={`glass-panel rounded-2xl p-5 border flex flex-col justify-between shadow-xl transition-all duration-300 ${
                            a.status === 'working' ? 'border-blue-500 animate-glow-blue' :
                            a.status === 'done' ? 'border-emerald-500/30' :
                            a.status === 'failed' ? 'border-rose-500/30' : 'border-slate-800'
                          }`}
                        >
                          <div>
                            <div className="flex items-center justify-between gap-3 mb-2">
                              <span className="text-xs font-bold text-slate-200 truncate max-w-[200px]" title={a.title || a.task_id}>
                                {a.title || a.task_id}
                              </span>
                              <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold uppercase ${
                                a.status === 'done' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                                a.status === 'failed' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                                a.status === 'working' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse' :
                                'bg-slate-800 text-slate-400 border border-slate-700/50'
                              }`}>
                                {a.status}
                              </span>
                            </div>

                            <p className="text-xs text-slate-400 mb-3 line-clamp-2 min-h-[32px]">{a.message || 'Initializing agent workspace...'}</p>

                            {a.branch && (
                              <a
                                href={`https://github.com/amkhar/GhostWriter/tree/${a.branch}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1.5 text-[10px] bg-blue-950/40 hover:bg-blue-900/40 px-2.5 py-1.5 rounded-lg border border-blue-900/50 hover:border-blue-700/50 text-blue-400 hover:text-blue-300 font-mono transition-all"
                              >
                                <svg className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
                                </svg>
                                <span className="truncate">GitHub Branch: {a.branch} ↗</span>
                              </a>
                            )}
                          </div>

                          <div className="mt-4 pt-3 border-t border-slate-800/60 flex flex-col gap-2">
                            <div className="flex items-center justify-between text-xs text-slate-500 font-mono">
                              {a.test_status && (
                                <span className="flex items-center gap-1.5">
                                  <span className={`w-1.5 h-1.5 rounded-full ${a.test_status === 'passed' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                                  Tests: <strong className="text-slate-400">{a.test_status}</strong>
                                </span>
                              )}
                              {a.diff && (
                                <span className="text-[10px] text-slate-400">
                                  Diff Lines: <strong className="text-emerald-400">{diffLinesCount}</strong>
                                </span>
                              )}
                            </div>

                            {a.diff && (
                              <div className="mt-2 flex flex-col">
                                <button
                                  onClick={() => toggleDiff(a.task_id)}
                                  className="w-full text-center text-xs font-semibold py-1.5 rounded bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 text-blue-400 hover:text-blue-300 transition-colors"
                                >
                                  {isExpanded ? 'Hide Code Diff' : 'View Code Diff'}
                                </button>

                                {isExpanded && (
                                  <div className="mt-2 text-left">
                                    <div className="flex justify-between items-center bg-[#090d16] px-3 py-1.5 rounded-t-lg border-x border-t border-slate-850">
                                      <span className="text-[10px] text-slate-500 font-mono">WORKSPACE DIFF</span>
                                      <button
                                        onClick={() => copyToClipboard(a.diff!, a.task_id)}
                                        className="text-[10px] text-blue-400 hover:text-blue-300 font-semibold"
                                      >
                                        {copiedTaskDiff === a.task_id ? 'Copied!' : 'Copy Diff'}
                                      </button>
                                    </div>
                                    <pre className="text-[10px] bg-[#090d16] p-3 rounded-b-lg border-x border-b border-slate-850 overflow-x-auto max-h-56 font-mono leading-relaxed">
                                      {renderDiff(a.diff)}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            )}

                            {a.error && (
                              <div className="mt-2 bg-rose-950/20 border border-rose-900/40 p-2.5 rounded-lg text-[10px] text-rose-300 font-mono break-all leading-normal">
                                Error: {a.error}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* 2. Skipped/Manual Tasks (Safety overrides required) */}
                {stageChecked(stages, 4) && skippedTasks.length > 0 && (
                  <div>
                    <div className="mb-3 pt-4 border-t border-slate-800/40">
                      <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
                        <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.75c0 5.592 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.57-.598-3.75h-.152c-3.196 0-6.1-1.249-8.25-3.286Zm0 13.036h.008v.008H12v-.008Z" />
                        </svg>
                        Manual Review Required ({skippedTasks.length})
                      </h3>
                      <p className="text-[11px] text-slate-500 mt-0.5">Tasks skipped by the safety classifier. Provide manual code guidance to override and auto-implement.</p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {skippedTasks.map(t => (
                        <div
                          key={t.id}
                          className="glass-panel rounded-2xl p-5 border border-amber-500/20 bg-amber-500/5 hover:border-amber-500/30 transition-all shadow-xl flex flex-col justify-between"
                        >
                          <div>
                            <div className="flex items-center justify-between gap-3 mb-2">
                              <span className="text-xs font-bold text-slate-200 truncate max-w-[200px]" title={t.title}>
                                {t.title}
                              </span>
                              <span className="text-[10px] px-2 py-0.5 rounded font-mono font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                Skipped
                              </span>
                            </div>

                            <p className="text-xs text-slate-400 mb-3">{t.description}</p>
                          </div>

                          <div className="mt-4 pt-3 border-t border-amber-500/10 flex flex-col gap-2.5">
                            {t.auto_doable_category && (
                              <div className="flex items-center gap-1.5 text-[10px] font-mono">
                                <span className="text-slate-500">Category:</span>
                                <span className="bg-slate-800 text-slate-300 border border-slate-700/50 px-2 py-0.5 rounded uppercase font-semibold tracking-wide">
                                  {t.auto_doable_category}
                                </span>
                              </div>
                            )}

                            {t.classification_reasoning && (
                              <div className="bg-[#111827]/60 border border-slate-800 rounded-lg p-3 text-[11px] text-slate-400 leading-relaxed">
                                <span className="font-bold text-slate-300 block mb-1">Classifier Analysis:</span>
                                {t.classification_reasoning}
                              </div>
                            )}

                            {/* Manual review input box */}
                            <div className="mt-2 bg-slate-900/60 p-3 rounded-lg border border-slate-800 flex flex-col gap-2">
                              <textarea
                                value={guidanceInputs[t.id] || ''}
                                onChange={e => setGuidanceInputs(prev => ({ ...prev, [t.id]: e.target.value }))}
                                placeholder="Describe how to code this change (guidance matches CLI)..."
                                className="w-full text-[11px] bg-slate-950 text-slate-200 border border-slate-800 rounded p-2 focus:border-amber-500/50 focus:outline-none placeholder-slate-600 resize-none h-14 font-sans leading-relaxed"
                              />
                              <button
                                onClick={() => handleOverride(t.id, guidanceInputs[t.id])}
                                disabled={!guidanceInputs[t.id]?.trim() || !runId}
                                className="w-full text-center text-xs font-bold py-1.5 rounded bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                Override & Auto-Implement
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ─── DETAIL VIEW (history drilldown) ───
  if (view === 'detail' && selectedRun) {
    const runTasks = selectedRun.tasks || JSON.parse(selectedRun.tasks_json || '[]');
    const runResults = selectedRun.agent_results || JSON.parse(selectedRun.results_json || '[]');
    return (
      <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col">
        <Nav onBack={() => { setView('home'); setSelectedRun(null); }} />
        <div className="max-w-4xl mx-auto w-full px-6 py-8 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-6 border-b border-slate-800 pb-4">
            <div>
              <h1 className="text-xl font-bold text-white">Historical Run {selectedRun.id}</h1>
              <p className="text-xs text-slate-500 mt-1">Executed at {new Date(selectedRun.started_at).toLocaleString()}</p>
            </div>
            <span className={`text-xs px-3 py-1 rounded-full font-bold uppercase border ${
              selectedRun.status === 'complete' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
            }`}>
              {selectedRun.status}
            </span>
          </div>

          {selectedRun.transcript && (
            <details className="mb-6 bg-slate-900/30 border border-slate-800/80 rounded-xl overflow-hidden shadow-md">
              <summary className="px-4 py-3 text-sm font-semibold text-slate-300 cursor-pointer hover:bg-slate-800/20 select-none">
                Original Standup Transcript Details
              </summary>
              <pre className="px-4 pb-4 pt-1 text-xs text-slate-400 whitespace-pre-wrap font-mono leading-relaxed bg-[#090d16]/30 border-t border-slate-850">
                {selectedRun.transcript}
              </pre>
            </details>
          )}

          {/* Detailed Run Report Summary (Markdown View) */}
          {selectedRun.report_md && (
            <div className="mb-8 bg-slate-900/40 border border-slate-800/80 rounded-2xl p-6 shadow-md">
              <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4 flex items-center gap-2">
                <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                </svg>
                Detailed Agentic Report Summary
              </h2>
              <div className="bg-[#090d16]/40 border border-slate-800/80 rounded-xl p-5 shadow-inner">
                <MarkdownReportView markdown={selectedRun.report_md} />
              </div>
            </div>
          )}

          <div className="space-y-4 mb-8">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Discovered Tasks ({runTasks.length})</h2>
            {runTasks.map((t: any) => (
              <div key={t.id} className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-5 shadow-sm flex flex-col justify-between">
                <div>
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <div className={`w-2.5 h-2.5 rounded-full ${t.auto_doable ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]' : 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.4)]'}`} />
                    <span className="text-sm font-bold text-slate-200">{t.title}</span>
                    {t.category && (
                      <span className="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700/50 uppercase tracking-wider font-semibold">
                        {t.category}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 ml-5.5 leading-relaxed">{t.description}</p>
                  {t.classification_reasoning && (
                    <p className="text-xs text-indigo-400/80 bg-indigo-500/5 border border-indigo-500/10 p-2.5 rounded-lg ml-5.5 mt-3 italic">
                      <strong>Classifier Reasoning:</strong> {t.classification_reasoning}
                    </p>
                  )}
                </div>

                {/* Allow overriding a task even on a completed historical run detail view! */}
                {!t.auto_doable && (
                  <div className="ml-5.5 mt-4 pt-3 border-t border-slate-800/60 max-w-md bg-slate-950/40 p-3 rounded-lg border border-slate-800">
                    <span className="text-[10px] font-bold text-slate-400 block mb-1">FORCE AUTO-IMPLEMENT FROM HISTORY</span>
                    <div className="flex flex-col gap-2">
                      <textarea
                        value={guidanceInputs[t.id] || ''}
                        onChange={e => setGuidanceInputs(prev => ({ ...prev, [t.id]: e.target.value }))}
                        placeholder="Describe how to code this change..."
                        className="w-full text-[10px] bg-slate-950 text-slate-200 border border-slate-800 rounded p-2 focus:border-amber-500/50 focus:outline-none placeholder-slate-700 resize-none h-12 font-sans"
                      />
                      <button
                        onClick={() => {
                          setView('running');
                          // initialize layout
                          setPipelineActive(false);
                          setStages([
                            { stage: 1, name: 'Ingest', status: 'complete', message: 'Loaded from history' },
                            { stage: 2, name: 'Extract', status: 'complete', message: 'Loaded from history' },
                            { stage: 3, name: 'Recurrence', status: 'complete', message: 'Loaded from history' },
                            { stage: 4, name: 'Classify', status: 'complete', message: 'Loaded from history' },
                            { stage: 5, name: 'Implement', status: 'running', message: 'Executing override task...' },
                          ]);
                          setTasks(runTasks);
                          setAgents(runResults.map((ar: any) => ({
                            task_id: ar.task_id,
                            status: ar.success ? 'done' : 'failed',
                            summary: ar.summary,
                            diff: ar.diff,
                            test_status: ar.test_status,
                            error: ar.error,
                          })));
                          handleOverride(t.id, guidanceInputs[t.id]);
                        }}
                        disabled={!guidanceInputs[t.id]?.trim()}
                        className="w-full text-center text-xs font-bold py-1 rounded bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Override & Implement
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {runResults.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Agent Workspaces & Diffs ({runResults.length})</h2>
              {runResults.map((r: any, i: number) => {
                const isExpanded = expandedDiffs[`history-${i}`] || false;
                return (
                  <div key={i} className={`bg-slate-900/40 border rounded-xl p-5 shadow-sm ${r.success ? 'border-emerald-500/20' : 'border-rose-500/20'}`}>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-mono font-bold text-slate-300">{r.task_id}</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                        r.success ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                      }`}>
                        {r.success ? 'success' : 'failed'}
                      </span>
                    </div>
                    {r.summary && <p className="text-xs text-slate-400 leading-relaxed mb-3">{r.summary}</p>}
                    <div className="flex items-center justify-between text-xs text-slate-500 font-mono">
                      {r.test_status && (
                        <span>Test run: <strong className="text-slate-400">{r.test_status}</strong></span>
                      )}
                      {r.branch && (
                        <a
                          href={`https://github.com/amkhar/GhostWriter/tree/${r.branch}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-blue-400 hover:text-blue-300 font-mono hover:underline"
                        >
                          Branch: {r.branch} ↗
                        </a>
                      )}
                    </div>
                    {r.diff && (
                      <div className="mt-3">
                        <button
                          onClick={() => toggleDiff(`history-${i}`)}
                          className="w-full text-center text-xs font-semibold py-1.5 rounded bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 text-blue-400 hover:text-blue-300 transition-colors"
                        >
                          {isExpanded ? 'Hide Code Diff' : 'View Code Diff'}
                        </button>
                        {isExpanded && (
                          <pre className="mt-2 text-[10px] bg-[#090d16] p-3 rounded-lg border border-slate-850 overflow-x-auto max-h-60 overflow-y-auto font-mono leading-relaxed">
                            {renderDiff(r.diff)}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  return null;
}

// ─── Sub-Components ───

function Nav({ onBack }: { onBack?: () => void }) {
  return (
    <header className="h-16 border-b border-slate-800/80 bg-[#0d1117] px-6 flex items-center justify-between flex-shrink-0 shadow-md">
      <div className="flex items-center gap-3">
        {onBack && (
          <button
            onClick={onBack}
            className="text-slate-400 hover:text-slate-200 mr-2 p-1.5 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
            👻 GhostWriter
          </span>
          <span className="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-750 font-semibold uppercase tracking-wider">
            v1.2 Agentic
          </span>
        </div>
      </div>
    </header>
  );
}

function TaskDetail({
  task,
  agent,
  expandedDiffs,
  toggleDiff,
  copyToClipboard,
  copiedTaskDiff,
}: {
  task: TaskItem;
  agent?: AgentResult;
  expandedDiffs: Record<string, boolean>;
  toggleDiff: (id: string) => void;
  copyToClipboard: (text: string, id: string) => void;
  copiedTaskDiff: string | null;
}) {
  const isExpanded = expandedDiffs[task.id] || false;
  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-1">Task Definition</h4>
        <p className="text-sm text-slate-300 leading-relaxed">{task.description}</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <h4 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-1">Safety Classification</h4>
          <span className={`inline-flex text-[10px] px-2.5 py-0.5 rounded border font-semibold ${
            task.auto_doable ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
          }`}>
            {task.auto_doable ? 'Auto-Implement Safe' : 'Requires Manual Intervention'}
          </span>
        </div>
        {task.auto_doable_category && (
          <div>
            <h4 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-1">Task Category</h4>
            <span className="inline-flex text-[10px] bg-slate-800 text-slate-300 border border-slate-700/50 px-2.5 py-0.5 rounded uppercase tracking-wider font-mono">
              {task.auto_doable_category}
            </span>
          </div>
        )}
      </div>

      {task.classification_reasoning && (
        <div className="bg-[#111827]/40 border border-slate-800 rounded-xl p-3.5 italic text-xs text-slate-400">
          <strong>Classifier Reasoning:</strong> {task.classification_reasoning}
        </div>
      )}

      {agent && (
        <div className={`border rounded-xl p-5 shadow-sm space-y-3 ${
          agent.status === 'done' ? 'border-emerald-500/20 bg-emerald-950/5' :
          agent.status === 'failed' ? 'border-rose-500/20 bg-rose-950/5' : 'border-blue-500/20 bg-blue-950/5 animate-pulse'
        }`}>
          <div className="flex items-center justify-between border-b border-slate-850 pb-2">
            <span className="text-xs font-bold font-mono text-slate-200">Agent Workspace</span>
            <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold uppercase ${
              agent.status === 'done' ? 'bg-emerald-500/10 text-emerald-400' :
              agent.status === 'failed' ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'
            }`}>
              {agent.status}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4 text-xs font-mono text-slate-400">
            {agent.branch && (
              <div>
                <span className="text-[10px] text-slate-500 block mb-0.5">GIT BRANCH</span>
                <a
                  href={`https://github.com/amkhar/GhostWriter/tree/${agent.branch}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:text-blue-300 font-bold font-mono transition-all hover:underline block truncate"
                >
                  {agent.branch} ↗
                </a>
              </div>
            )}
            {agent.test_status && (
              <div>
                <span className="text-[10px] text-slate-500 block mb-0.5">VERIFICATION TESTS</span>
                <span className={`font-bold ${agent.test_status === 'passed' ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {agent.test_status}
                </span>
              </div>
            )}
          </div>

          {agent.summary && (
            <div className="text-xs text-slate-300 leading-relaxed bg-slate-950/30 p-3 rounded-lg border border-slate-850">
              <strong>Summary of Changes:</strong> {agent.summary}
            </div>
          )}

          {agent.diff && (
            <div className="mt-3">
              <button
                onClick={() => toggleDiff(task.id)}
                className="w-full text-center text-xs font-semibold py-1.5 rounded bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 text-blue-400 hover:text-blue-300 transition-colors"
              >
                {isExpanded ? 'Hide Code Diff' : 'View Code Diff'}
              </button>
              {isExpanded && (
                <div className="mt-2 text-left">
                  <div className="flex justify-between items-center bg-[#090d16] px-3 py-1.5 rounded-t-lg border-x border-t border-slate-850">
                    <span className="text-[10px] text-slate-500 font-mono">WORKSPACE DIFF</span>
                    <button
                      onClick={() => copyToClipboard(agent.diff!, task.id)}
                      className="text-[10px] text-blue-400 hover:text-blue-300 font-semibold"
                    >
                      {copiedTaskDiff === task.id ? 'Copied!' : 'Copy Diff'}
                    </button>
                  </div>
                  <pre className="text-[10px] bg-[#090d16] p-3 rounded-b-lg border-x border-b border-slate-850 overflow-x-auto max-h-80 overflow-y-auto font-mono leading-relaxed">
                    {renderDiff(agent.diff)}
                  </pre>
                </div>
              )}
            </div>
          )}

          {agent.error && (
            <div className="bg-rose-950/20 border border-rose-900/40 p-3.5 rounded-lg text-xs text-rose-300 font-mono break-all leading-normal">
              <strong>Error Traceback:</strong>
              <div className="mt-1">{agent.error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Custom Markdown Viewer Component for Detailed Report Summary ───

function MarkdownReportView({ markdown }: { markdown: string }) {
  if (!markdown) return <p className="text-xs text-slate-500 italic">No report summary available.</p>;

  const lines = markdown.split('\n');
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let codeLang = '';

  const parsedElements = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        inCodeBlock = false;
        const codeText = codeLines.join('\n');
        const isDiff = codeLang === 'diff';
        parsedElements.push(
          <pre key={`code-${i}`} className="text-[10px] bg-[#05080e] p-3 rounded-lg border border-slate-850 overflow-x-auto my-3 font-mono leading-relaxed">
            {isDiff ? renderDiff(codeText) : codeText}
          </pre>
        );
        codeLines = [];
      } else {
        inCodeBlock = true;
        codeLang = line.replace('```', '').trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (line.trim() === '') {
      continue;
    }

    if (line.startsWith('# ')) {
      parsedElements.push(<h3 key={i} className="text-base font-extrabold text-white border-b border-slate-800 pb-2 mt-5 mb-3">{line.substring(2)}</h3>);
    } else if (line.startsWith('## ')) {
      parsedElements.push(<h4 key={i} className="text-sm font-bold text-slate-200 mt-4 mb-2">{line.substring(3)}</h4>);
    } else if (line.startsWith('### ')) {
      parsedElements.push(<h5 key={i} className="text-xs font-semibold text-slate-300 mt-3.5 mb-1.5">{line.substring(4)}</h5>);
    } else if (line.trim().startsWith('- ')) {
      const content = line.trim().substring(2);
      parsedElements.push(
        <div key={i} className="flex items-start gap-2 text-xs text-slate-300 pl-3 py-0.5 leading-relaxed">
          <span className="text-blue-500 font-bold select-none">•</span>
          <span>{parseBoldText(content)}</span>
        </div>
      );
    } else {
      parsedElements.push(<p key={i} className="text-xs text-slate-400 my-1.5 leading-relaxed">{parseBoldText(line)}</p>);
    }
  }

  return <div className="space-y-1">{parsedElements}</div>;
}

function parseBoldText(text: string) {
  const parts = text.split('**');
  return parts.map((part, idx) => {
    if (idx % 2 === 1) {
      return <strong key={idx} className="text-slate-100 font-semibold bg-slate-900/60 px-1 py-0.5 rounded border border-slate-800/40">{part}</strong>;
    }
    return part;
  });
}

// Helper to determine if a stage has completed or run
function stageChecked(stages: StageInfo[], stageNum: number): boolean {
  const stage = stages.find(s => s.stage === stageNum);
  return stage ? (stage.status === 'complete' || stage.status === 'running') : false;
}

// Git diff coloring helper
function renderDiff(diffText: string) {
  const lines = diffText.split('\n');
  return lines.map((line, idx) => {
    let className = 'diff-line-context';
    if (line.startsWith('+') && !line.startsWith('+++')) {
      className = 'diff-line-added block px-2 py-0.5 rounded';
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      className = 'diff-line-removed block px-2 py-0.5 rounded';
    } else if (line.startsWith('@@') || line.startsWith('diff') || line.startsWith('index')) {
      className = 'text-indigo-400 font-bold block py-0.5';
    }
    return (
      <span key={idx} className={className}>
        {line}
        {'\n'}
      </span>
    );
  });
}
