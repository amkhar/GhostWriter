'use client';

import { useState, useEffect, useRef } from 'react';

type View = 'home' | 'running' | 'detail';
type TaskItem = { id: string; title: string; description: string; reason: string; auto_doable: boolean; auto_doable_category?: string; classification_reasoning?: string };
type AgentResult = { task_id: string; status: string; summary?: string; diff?: string; test_status?: string; title?: string; message?: string; branch?: string; error?: string };
type StageInfo = { stage: number; name: string; status: string; message: string; stats?: any; tasks?: TaskItem[] };
type RecStatus = { active: boolean; lines: string[]; partial: string; elapsed: number };

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
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (recording) {
      pollRef.current = setInterval(async () => {
        try { const r = await fetch('/api/recording/status'); if (r.ok) setRecStatus(await r.json()); } catch {}
      }, 400);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [recording]);

  useEffect(() => { loadRuns(); }, []);

  const loadRuns = () => fetch('/api/pipeline/runs').then(r => r.json()).then(setRuns).catch(() => {});

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
    setStages([]); setTasks([]); setAgents([]); setStats({});

    const url = `/api/pipeline/stream?transcript=${encodeURIComponent(transcript)}&repo=${encodeURIComponent('/Users/himmi/casacadia/GhostWriter')}`;
    const es = new EventSource(url);

    es.addEventListener('stage', (e) => {
      const d = JSON.parse(e.data);
      setStages(prev => { const i = prev.findIndex(s => s.stage === d.stage); if (i >= 0) { const n = [...prev]; n[i] = d; return n; } return [...prev, d]; });
      if (d.tasks) setTasks(d.tasks);
      if (d.stats) setStats(d.stats);
    });
    es.addEventListener('agent', (e) => {
      const d = JSON.parse(e.data);
      setAgents(prev => { const i = prev.findIndex(a => a.task_id === d.task_id); if (i >= 0) { const n = [...prev]; n[i] = { ...n[i], ...d }; return n; } return [...prev, d]; });
    });
    es.addEventListener('complete', (e) => {
      const d = JSON.parse(e.data);
      if (d.tasks) setTasks(d.tasks);
      if (d.stats) setStats(d.stats);
      setPipelineActive(false); es.close(); loadRuns();
    });
    es.addEventListener('error', () => { setPipelineActive(false); es.close(); });
    es.onerror = () => { setPipelineActive(false); es.close(); };
  };

  const fmt = (s: number) => `${Math.floor(s/60).toString().padStart(2,'0')}:${(s%60).toString().padStart(2,'0')}`;

  const loadRunDetail = async (id: string) => {
    const res = await fetch(`/api/pipeline/runs/${id}`);
    if (res.ok) { setSelectedRun(await res.json()); setView('detail'); }
  };

  // ─── HOME VIEW ───
  if (view === 'home' && !recording) {
    return (
      <div className="min-h-screen bg-white flex flex-col">
        <Nav />
        <div className="flex-1 flex flex-col items-center justify-center px-6">
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Turn standups into shipped code</h1>
          <p className="mt-3 text-lg text-gray-500 max-w-lg text-center">Record your standup. GhostWriter identifies neglected tasks and implements the safe ones — each on its own branch.</p>
          <button onClick={startRec} className="mt-10 w-20 h-20 rounded-full bg-gray-900 hover:bg-gray-800 transition-all shadow-xl hover:shadow-2xl flex items-center justify-center group">
            <svg className="w-8 h-8 text-white group-hover:scale-110 transition-transform" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          </button>
          <p className="mt-4 text-sm text-gray-400">Click to start recording</p>

          {runs.length > 0 && (
            <div className="mt-16 w-full max-w-2xl">
              <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-3">Recent runs</h2>
              <div className="space-y-1">
                {runs.slice(0, 5).map((r: any) => (
                  <div key={r.id} onClick={() => loadRunDetail(r.id)} className="flex items-center justify-between px-4 py-3 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full ${r.status === 'complete' ? 'bg-green-500' : r.status === 'failed' ? 'bg-red-400' : 'bg-blue-400'}`} />
                      <span className="text-sm text-gray-700">{r.transcript_preview || `Run ${r.id}`}</span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-gray-400">
                      {r.stats?.api_calls && <span>{r.stats.api_calls} calls</span>}
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
      <div className="min-h-screen bg-white flex flex-col">
        <Nav />
        <div className="flex-1 flex flex-col items-center justify-center px-6 max-w-2xl mx-auto w-full">
          <div className="flex items-center gap-3 mb-6">
            <span className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
            <span className="text-lg font-medium text-gray-900">Recording</span>
            <span className="text-lg text-gray-400 font-mono">{fmt(recStatus.elapsed)}</span>
          </div>
          <div className="w-full bg-gray-50 border border-gray-200 rounded-xl p-6 min-h-[320px] max-h-[420px] overflow-y-auto">
            {recStatus.lines.length === 0 && !recStatus.partial && <p className="text-gray-300 text-sm">Listening...</p>}
            {recStatus.lines.map((l, i) => <p key={i} className="text-sm text-gray-700 leading-relaxed mb-1">{l}</p>)}
            {recStatus.partial && <p className="text-sm text-gray-400 italic">{recStatus.partial}</p>}
          </div>
          <button onClick={stopRec} className="mt-6 px-6 py-3 bg-gray-900 text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition-colors">
            Stop and process
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

    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Nav onBack={() => { setView('home'); loadRuns(); }} />

        {/* Stats strip */}
        <div className="bg-white border-b border-gray-200 px-6 py-3">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-6 text-sm">
              {pipelineActive && <span className="flex items-center gap-2 text-blue-600"><span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"/>Running</span>}
              {!pipelineActive && agents.length > 0 && <span className="text-green-600 font-medium">Complete</span>}
              <span className="text-gray-500"><strong className="text-gray-900">{tasks.length}</strong> tasks found</span>
              <span className="text-gray-500"><strong className="text-gray-900">{agents.length}</strong> experiments</span>
            </div>
            <div className="flex gap-5 text-xs text-gray-400">
              <span>{stats.files_analyzed || 0} files analyzed</span>
              <span>{stats.api_calls || 0} API calls</span>
              <span>{stats.lines_changed || 0} lines changed</span>
            </div>
          </div>
        </div>

        <div className="flex-1 flex max-w-7xl mx-auto w-full">
          {/* Left sidebar: Pipeline stages */}
          <aside className="w-56 border-r border-gray-200 bg-white p-4 flex-shrink-0">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Pipeline</h3>
            {stages.map(s => (
              <div key={s.stage} className="flex items-center gap-2 py-2">
                {s.status === 'running' ? <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse flex-shrink-0"/> : s.status === 'complete' ? <span className="w-2 h-2 bg-green-500 rounded-full flex-shrink-0"/> : <span className="w-2 h-2 bg-gray-200 rounded-full flex-shrink-0"/>}
                <span className="text-xs text-gray-700">{s.name}</span>
              </div>
            ))}
            <div className="mt-6 pt-4 border-t border-gray-100">
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Tasks</h3>
              {tasks.map(t => (
                <div key={t.id} onClick={() => setSelectedTask(t.id)} className={`flex items-center gap-2 py-1.5 px-2 rounded cursor-pointer text-xs ${selectedTask === t.id ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'}`}>
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${t.auto_doable ? 'bg-green-500' : 'bg-gray-300'}`}/>
                  <span className="truncate">{t.title}</span>
                </div>
              ))}
            </div>
          </aside>

          {/* Main content */}
          <main className="flex-1 p-6 overflow-y-auto">
            {/* Parallel execution header */}
            {(working.length > 0 || queued.length > 0) && (
              <div className="mb-6 p-4 bg-blue-50 border border-blue-100 rounded-xl">
                <div className="flex items-center gap-2 mb-2">
                  <svg className="w-4 h-4 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                  <span className="text-sm font-medium text-blue-900">{working.length} experiment{working.length !== 1 ? 's' : ''} running in parallel</span>
                  {queued.length > 0 && <span className="text-xs text-blue-500 ml-2">({queued.length} queued)</span>}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                  {working.map(a => (
                    <div key={a.task_id} className="bg-white rounded-lg border border-blue-200 p-3">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"/>
                        <span className="text-xs font-medium text-gray-800 truncate">{a.title || a.task_id}</span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1 truncate">{a.message}</p>
                      {a.branch && <p className="text-xs text-blue-500 mt-1 font-mono">{a.branch}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Selected task detail */}
            {selectedTask && tasks.find(t => t.id === selectedTask) ? (
              <TaskDetail task={tasks.find(t => t.id === selectedTask)!} agent={agents.find(a => a.task_id === selectedTask)} />
            ) : (
              <>
                {/* Completed experiments */}
                {done.length > 0 && (
                  <div className="mb-6">
                    <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Completed ({done.length})</h3>
                    <div className="space-y-2">
                      {done.map(a => <AgentCard key={a.task_id} agent={a} onClick={() => setSelectedTask(a.task_id)} />)}
                    </div>
                  </div>
                )}

                {/* Failed experiments */}
                {failed.length > 0 && (
                  <div className="mb-6">
                    <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Failed ({failed.length})</h3>
                    <div className="space-y-2">
                      {failed.map(a => <AgentCard key={a.task_id} agent={a} onClick={() => setSelectedTask(a.task_id)} />)}
                    </div>
                  </div>
                )}

                {/* Empty state */}
                {agents.length === 0 && pipelineActive && (
                  <div className="text-center py-20">
                    <svg className="w-6 h-6 animate-spin text-gray-300 mx-auto mb-3" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                    <p className="text-sm text-gray-400">Analyzing your standup...</p>
                  </div>
                )}

                {/* Pipeline complete summary */}
                {!pipelineActive && agents.length > 0 && (
                  <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-xl text-center">
                    <p className="text-sm text-gray-700 font-medium">{done.length} experiment{done.length !== 1 ? 's' : ''} shipped, {failed.length} failed</p>
                    <p className="text-xs text-gray-400 mt-1">Each successful task was pushed to its own branch</p>
                  </div>
                )}
              </>
            )}
          </main>
        </div>
      </div>
    );
  }

  // ─── DETAIL VIEW (history drilldown) ───
  if (view === 'detail' && selectedRun) {
    const runTasks = selectedRun.tasks || JSON.parse(selectedRun.tasks_json || '[]');
    const runResults = selectedRun.agent_results || JSON.parse(selectedRun.results_json || '[]');
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Nav onBack={() => { setView('home'); setSelectedRun(null); }} />
        <div className="max-w-4xl mx-auto w-full px-6 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-xl font-semibold text-gray-900">Run {selectedRun.id}</h1>
              <p className="text-sm text-gray-500">{new Date(selectedRun.started_at).toLocaleString()}</p>
            </div>
            <span className={`text-xs px-3 py-1 rounded-full font-medium ${selectedRun.status === 'complete' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>{selectedRun.status}</span>
          </div>

          {selectedRun.transcript && (
            <details className="mb-6 bg-white border border-gray-200 rounded-lg">
              <summary className="px-4 py-3 text-sm font-medium text-gray-700 cursor-pointer">Transcript</summary>
              <pre className="px-4 pb-4 text-xs text-gray-600 whitespace-pre-wrap">{selectedRun.transcript}</pre>
            </details>
          )}

          <div className="space-y-3 mb-8">
            <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide">Tasks ({runTasks.length})</h2>
            {runTasks.map((t: any) => (
              <div key={t.id} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-1">
                  <div className={`w-2 h-2 rounded-full ${t.auto_doable ? 'bg-green-500' : 'bg-gray-300'}`} />
                  <span className="text-sm font-medium text-gray-900">{t.title}</span>
                  {t.category && <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">{t.category}</span>}
                </div>
                <p className="text-xs text-gray-500 ml-4">{t.description}</p>
                {t.reasoning && <p className="text-xs text-gray-400 ml-4 mt-1 italic">{t.reasoning}</p>}
              </div>
            ))}
          </div>

          {runResults.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide">Agent Results ({runResults.length})</h2>
              {runResults.map((r: any, i: number) => (
                <div key={i} className={`bg-white border rounded-lg p-4 ${r.success ? 'border-green-200' : 'border-red-200'}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-gray-800">{r.task_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${r.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>{r.success ? 'success' : 'failed'}</span>
                  </div>
                  {r.summary && <p className="text-xs text-gray-600">{r.summary}</p>}
                  {r.test_status && <p className="text-xs text-gray-400 mt-1">Tests: {r.test_status}</p>}
                  {r.diff && (
                    <details className="mt-2">
                      <summary className="text-xs text-blue-600 cursor-pointer">View diff</summary>
                      <pre className="mt-2 text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-60 overflow-y-auto">{r.diff}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return null;
}

// ─── Components ───

function Nav({ onBack }: { onBack?: () => void }) {
  return (
    <header className="h-14 border-b border-gray-200 bg-white px-6 flex items-center justify-between flex-shrink-0">
      <div className="flex items-center gap-3">
        {onBack && (
          <button onClick={onBack} className="text-gray-400 hover:text-gray-600 mr-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/></svg>
          </button>
        )}
        <span className="text-base font-semibold text-gray-900">GhostWriter</span>
      </div>
    </header>
  );
}

function AgentCard({ agent, onClick }: { agent: AgentResult; onClick: () => void }) {
  const ghUrl = agent.branch ? `https://github.com/amkhar/GhostWriter/tree/${agent.branch}` : null;
  return (
    <div onClick={onClick} className={`bg-white border rounded-xl p-4 cursor-pointer transition-all hover:shadow-sm ${agent.status === 'working' ? 'border-blue-200' : agent.status === 'done' ? 'border-green-200' : 'border-red-200'}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {agent.status === 'working' && <svg className="w-3.5 h-3.5 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>}
          {agent.status === 'done' && <span className="w-3.5 h-3.5 text-green-500"><svg fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg></span>}
          <span className="text-sm font-medium text-gray-900">{agent.title || agent.task_id}</span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${agent.status === 'done' ? 'bg-green-50 text-green-700' : agent.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-600'}`}>{agent.status}</span>
      </div>
      {agent.summary && <p className="text-xs text-gray-600 mb-2">{agent.summary}</p>}
      <div className="flex items-center gap-4 text-xs text-gray-400">
        {agent.branch && (
          <a href={ghUrl || '#'} target="_blank" rel="noopener" onClick={e => e.stopPropagation()} className="font-mono text-blue-500 hover:text-blue-700 hover:underline">{agent.branch}</a>
        )}
        {agent.test_status && <span>tests: {agent.test_status}</span>}
        {agent.diff && <span>+{agent.diff.split('\n').filter(l => l.startsWith('+')).length} / -{agent.diff.split('\n').filter(l => l.startsWith('-')).length}</span>}
      </div>
    </div>
  );
}

function TaskDetail({ task, agent }: { task: TaskItem; agent?: AgentResult }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900 mb-1">{task.title}</h2>
      <p className="text-sm text-gray-500 mb-4">{task.description}</p>
      <div className="flex gap-2 mb-6">
        {task.auto_doable ? <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-1 rounded">auto-doable</span> : <span className="text-xs bg-gray-100 text-gray-500 px-2 py-1 rounded">skipped</span>}
        {task.auto_doable_category && <span className="text-xs bg-gray-50 text-gray-500 px-2 py-1 rounded">{task.auto_doable_category}</span>}
      </div>
      {task.classification_reasoning && <p className="text-xs text-gray-400 mb-4 italic">Classification: {task.classification_reasoning}</p>}

      {agent && (
        <div className={`border rounded-lg p-4 ${agent.status === 'done' ? 'border-green-200 bg-green-50/30' : agent.status === 'failed' ? 'border-red-200 bg-red-50/30' : 'border-blue-200 bg-blue-50/30'}`}>
          <div className="flex items-center gap-2 mb-2">
            {agent.status === 'working' && <svg className="w-3.5 h-3.5 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>}
            <span className="text-sm font-medium text-gray-800">Agent: {agent.status}</span>
            {agent.test_status && <span className="text-xs bg-white px-2 py-0.5 rounded border">{agent.test_status}</span>}
          </div>
          {agent.summary && <p className="text-sm text-gray-700">{agent.summary}</p>}
          {agent.diff && (
            <pre className="mt-3 text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-80 overflow-y-auto">{agent.diff}</pre>
          )}
          {agent.status === 'failed' && <p className="text-xs text-red-600 mt-2">{agent.message}</p>}
        </div>
      )}
    </div>
  );
}
