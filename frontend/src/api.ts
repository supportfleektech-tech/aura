/* AURA OS API client — relative URLs (Vite proxies /api to the backend). */

export const API = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text.slice(0, 200) || res.statusText}`);
  }
  return (await res.json()) as T;
}

export const get = <T,>(p: string) => req<T>(p);
export const post = <T,>(p: string, body?: unknown) =>
  req<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(p: string, body: unknown) =>
  req<T>(p, { method: "PATCH", body: JSON.stringify(body) });
export const put = <T,>(p: string, body: unknown) =>
  req<T>(p, { method: "PUT", body: JSON.stringify(body) });
export const del = <T,>(p: string) => req<T>(p, { method: "DELETE" });

/* ---------------- types ---------------- */
export type OrbState =
  | "idle" | "listening" | "thinking" | "retrieving" | "working" | "seeing"
  | "waiting_approval" | "success" | "warning" | "error" | "offline";

export interface PlanStep { id: string; label: string; status: string }
export interface ChatMsg {
  id: string; role: "user" | "assistant" | "system" | "plan" | "approval" | "error";
  text: string; ts: number; steps?: PlanStep[]; memories?: { id: number; title: string; relevance: number }[];
  approval?: { id: number; risk: string; title: string; drafts: { to: string; subject: string; body: string }[] };
  model?: string;
  files?: { id: number; name: string }[];
  vision?: { file: string; status: string; model?: string }[];
  missions?: MissionProgress[];
  thinking?: string[];
}

export interface MissionProgress {
  id: number; goal: string; status: string; step_idx: number;
  steps: { label: string; status: string; note?: string }[];
}
export interface Analytics {
  spending: { by_currency: { currency: string; month: number; last_month: number; delta_pct: number | null }[];
    by_day: { day: string; currency: string; total: number }[];
    by_category: { category: string; currency: string; total: number }[] };
  tasks: { done_14d: { day: string; n: number }[]; created_30: number; done_30: number;
    completion_rate: number | null; overdue_now: number; by_status: Record<string, number> };
  habits: { name: string; streak: number; last_done: string; done_today: boolean }[];
  sleep: { avg_7d: number | null; nights: { date: string; hours: number }[] };
  mood: { avg_14d: number | null; points: { day: string; score: number }[] };
  activity: { runs_14d: { day: string; n: number }[]; messages_14d: { day: string; n: number }[] };
  forecast: { spending_next_7d: { currency: string; amount: number; basis: string } | null;
    task_velocity_per_day: number | null; tasks_next_7d: number | null;
    sleep_trend: number | null; mood_trend: number | null };
}
export interface Dashboard {
  priorities: Task[]; counts: Record<string, number>; projects: Project[]; clients: Client[];
  activity: Activity[]; notifications: Note[]; gateway: { platform: string; status: string; account: string }[];
  timeblocks: TimeBlock[]; insights: Record<string, string>; memory_by_domain: Record<string, number>;
}
export interface Task { id: number; title: string; description: string; status: string; priority: string; due_at: string | null; project_id: number | null; client_id: number | null; domain: string; client_name?: string; project_name?: string }
export interface Client { id: number; name: string; org: string; email: string; phone: string; health: string; notes: string; contract_value: number; open_projects?: number; open_tasks?: number }
export interface Project { id: number; name: string; client_id: number | null; client_name?: string; status: string; progress: number; deadline: string | null; description: string; health: string; milestones?: Milestone[] }
export interface Milestone { id: number; title: string; status: string; due_at: string | null }
export interface Memory { id: number; domain: string; mtype: string; title: string; content: string; source: string; confidence: number; importance: number; sensitivity: string; created_at: string; relevance?: number; why_used?: string }
export interface Activity { id: number; kind: string; domain: string; title: string; detail: string; severity: string; source: string; created_at: string }
export interface Note { id: number; title: string; body: string; level: string; read: number; created_at: string }
export interface Automation { id: number; name: string; trigger_kind: string; trigger_config: string; action_kind: string; action_config: string; status: string; last_run: string | null; next_run: string | null; success_count: number; fail_count: number }
export interface TimeBlock { id: number; title: string; starts_at: string; ends_at: string; kind: string }
export interface GwIntegration { platform: string; status: string; account: string; last_test: string; mode: string; configured: boolean; missing: string[]; fields: Record<string, string>; last_error: string; last_ok: string }
export interface Briefing { id: number; name: string; kind: string; prompt: string; enabled: number; last_run: string | null; last_model: string; runs?: number }
export interface BriefRun { id: number; briefing_id: number | null; briefing_name: string | null; kind: string; output: string; model: string; ms: number; created_at: string }
export interface Session { id: string; title: string; domain: string; created_at: string; updated_at: string; pinned: boolean | number; starred: boolean | number; has_summary: boolean | number; n: number }
export interface UndoEntry { id: number; at: string; tool: string; op: string; tbl: string; row_id: string; summary: string }
export interface MissionStep { kind: string; label: string; tool?: string; args?: Record<string, unknown>; drafts_from?: number; status: string; note?: string; approval_id?: number }
export interface Mission { id: number; goal: string; status: string; steps: MissionStep[]; step_idx: number; needs_review: boolean | number; result: string; created_at: string; schedule_json?: string; next_run_at?: string }
export interface MissionRun { id: number; mission_id: number; started_at: string; finished_at: string; status: string; summary: string }
export interface HaEntity { entity_id: string; state: string; attributes?: { friendly_name?: string; unit_of_measurement?: string; [k: string]: unknown } }
export interface HaStatus { platform: string; status: string; account: string; last_test: string | null; mode: string; configured: boolean; missing: string[]; fields: Record<string, string>; last_error: string; last_ok: string }
export interface Opportunity { key: string; type: string; title: string; detail: string; reasons: string[]; importance: number; urgency: number; confidence: number; disruption: number; score: number; ref: string; dismissed?: boolean ; action?: { kind: string; label?: string; view?: string; text?: string; goal?: string; every?: string } }
export interface MailAccount { id: number; name: string; host: string; port: number; username: string; mode: string; status: string; has_password: boolean; unseen: number; last_sync: string | null; last_error: string }
export interface Mail { id: number; account_id: number; sender: string; subject: string; snippet: string; mail_date: string; seen: number; triage: string; triage_reason: string }
export interface MailFull extends Mail { body: string; recipients: string; message_id: string }
export interface Cal { id: number; name: string; source: string; color: string; status: string; fields: Record<string, string>; secrets_set: Record<string, boolean>; last_sync: string | null; last_error: string }
export interface CalEvent { id: number; calendar_id: number; calendar_name?: string; calendar_color?: string; uid: string; title: string; description: string; location: string; starts_at: string; ends_at: string; all_day: number }
export interface GwEvent { platform: string; direction: string; text: string; created_at: string; event_id?: string }

/* ---------------- SSE chat ---------------- */
export interface ChatEvents {
  onOrb?: (s: OrbState) => void;
  onPlan?: (p: { intent: string; domain: string; steps: PlanStep[]; session_id: string }) => void;
  onStep?: (s: { id: string; status: string }) => void;
  onToken?: (t: string) => void;
  onApproval?: (a: ChatMsg["approval"]) => void;
  onResult?: (r: { text: string; model: string; engine?: string; redacted_memories?: number; memories_used: ChatMsg["memories"]; approval: ChatMsg["approval"] }) => void;
  onMemory?: (m: { stored: { id: number; title: string }[] }) => void;
  onFacts?: (f: { stored: { id: number; title: string }[] }) => void;
  onVision?: (v: { file: string; status: string; model?: string }) => void;
  onMission?: (m: MissionProgress) => void;
  onError?: (e: string) => void;
  onDone?: (d: { session_id: string }) => void;
  onThinking?: (t: { text: string }) => void;
  /** A leading-slash command was executed server-side instead of the orchestrator. */
  onSlash?: (r: SlashResult) => void;
}

export async function chatStream(message: string, session_id: string | null, ev: ChatEvents, attachments: unknown[] = [], signal?: AbortSignal) {
  const res = await fetch(API + "/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id, attachments }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", curEvent = "";
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    signal?.throwIfAborted();
    for (;;) {
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        let data = "";
        for (const line of part.split("\n")) {
          if (line.startsWith("event:")) curEvent = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        try {
          const d = JSON.parse(data);
          if (curEvent === "orb") ev.onOrb?.(d.state);
          else if (curEvent === "plan") ev.onPlan?.(d);
          else if (curEvent === "step") ev.onStep?.(d);
          else if (curEvent === "token") ev.onToken?.(d.text);
          else if (curEvent === "thinking") ev.onThinking?.(d);
          else if (curEvent === "approval") ev.onApproval?.(d);
          else if (curEvent === "result") ev.onResult?.(d);
          else if (curEvent === "memory") ev.onMemory?.(d);
          else if (curEvent === "facts") ev.onFacts?.(d);
          else if (curEvent === "vision") ev.onVision?.(d);
          else if (curEvent === "mission") ev.onMission?.(d);
          else if (curEvent === "done") ev.onDone?.(d);
          else if (curEvent === "slash") ev.onSlash?.(d as SlashResult);
        } catch { /* keep-alive */ }
      }
    }
  } finally {
    signal?.removeEventListener("abort", cancel);
    try { void reader.cancel().catch(() => undefined); } catch {}
    try { reader.releaseLock(); } catch {}
  }
}

/* ---------------- slash commands (spec §3, FR-CMD-004/005) ------------- */
export type SlashCommandT = { name: string; category: string; summary: string; example: string; arg: string };
export type SlashResult = {
  handled: boolean; ok: boolean; command: string;
  result: unknown; text: string; view: string | null;
};

/* ---------------- api surface ---------------- */
export const api = {
  slash: {
    catalog: () => get<{ commands: SlashCommandT[] }>("/slash"),
    execute: (text: string) => post<SlashResult>("/slash/execute", { text }),
    saveCustom: (name: string, prompt: string, view = "") =>
      post<{ name: string }>("/slash/custom", { name, prompt, view }),
    deleteCustom: (name: string) => del<{ ok: boolean }>(`/slash/custom/${encodeURIComponent(name)}`),
  },
  me: {
    get: () => get<{ name: string; role: string; location: string; version: string }>("/me"),
    update: (b: Record<string, string>) => patch<{ name: string; role: string; location: string; version: string }>("/me", b),
  },
  health: () => get<{ ok: boolean; services: { name: string; status: string; detail: string }[]; metrics: Record<string, number>; active_model?: { backend: string; provider: string; model: string; privacy_mode: string; local_online: boolean; cloud_configured: boolean } }>("/health"),
  costs: () => get<any>("/costs"),
  analytics: { overview: () => get<Analytics>("/analytics/overview") },
  dashboard: () => get<Dashboard>("/dashboard"),
  search: (q: string, opts?: { type?: string; from?: string; to?: string }) => {
    const p = new URLSearchParams({ q });
    if (opts?.type) p.set("type", opts.type);
    if (opts?.from) p.set("frm", opts.from);
    if (opts?.to) p.set("to", opts.to);
    return get<{ results: { type: string; id: number; title: string; snippet: string; domain: string; relevance: number; matched?: string }[]; ms: number }>("/search?" + p.toString());
  },
  tasks: {
    list: (qs = "") => get<{ tasks: Task[] }>("/tasks" + qs),
    create: (t: Partial<Task>) => post<Task>("/tasks", t),
    update: (id: number, p: Partial<Task>) => patch<Task>(`/tasks/${id}`, p),
    remove: (id: number) => del(`/tasks/${id}`),
    overdue: () => get<{ overdue: Task[]; count: number }>("/tasks/overdue/list"),
  },
  clients: {
    list: () => get<{ clients: Client[] }>("/clients"),
    create: (c: Partial<Client>) => post<Client>("/clients", c),
    update: (id: number, p: Partial<Client>) => patch<Client>(`/clients/${id}`, p),
    remove: (id: number) => del(`/clients/${id}`),
    get: (id: number) => get<Client & { projects: Project[]; tasks: Task[] }>(`/clients/${id}`),
  },
  projects: {
    list: () => get<{ projects: Project[] }>("/projects"),
    create: (p: Partial<Project>) => post<Project>("/projects", p),
    update: (id: number, p: Partial<Project>) => patch<Project>(`/projects/${id}`, p),
    remove: (id: number) => del(`/projects/${id}`),
    milestone: (id: number, m: Partial<Milestone>) => post(`/projects/${id}/milestones`, m),
  },
  career: {
    overview: () => get<{ resumes: { id: number; name: string; version: number; ats_score: number; created_at: string }[]; applications: { id: number; company: string; role: string; stage: string; notes: string }[]; interviews: { id: number; company: string; role: string; score: number | null; feedback: string }[]; today_blocks: TimeBlock[]; tasks: Task[]; pipeline: Record<string, number> }>("/career/overview"),
    analyze: (b: { text: string; job_description?: string; name?: string }) => post<{ ats_score: number; word_count: number; quantified_bullets: number; action_verbs: number; recommendations: string[] }>("/career/resumes/analyze", b),
    addApp: (a: Record<string, string>) => post("/career/applications", a),
    updateApp: (id: number, p: Record<string, string>) => patch(`/career/applications/${id}`, p),
    questions: (role: string) => get<{ questions: string[] }>(`/career/interviews/questions?role=${encodeURIComponent(role)}`),
    addInterview: (iv: Record<string, unknown>) => post("/career/interviews", iv),
    blocks: () => get<{ blocks: TimeBlock[] }>("/career/blocks"),
    planBlocks: () => post<{ created: { title: string; starts_at: string; ends_at: string }[] }>("/career/blocks/plan", {}),
    addBlock: (b: Partial<TimeBlock>) => post("/career/blocks", b),
    delBlock: (id: number) => del(`/career/blocks/${id}`),
  },
  personal: {
    overview: () => get<{ journal: { id: number; title: string; body: string; mood: string; created_at: string }[]; goals: { id: number; domain: string; title: string; target: string; progress: number; status: string }[]; expenses: { id: number; category: string; amount: number; currency: string; note: string; created_at: string }[]; habits: { id: number; name: string; streak: number; last_done: string | null }[]; sleep: { id: number; date: string; bedtime: string | null; wake_at: string | null; hours: number; quality: string }[]; spending_total: number }>("/personal/overview"),
    journal: (j: Record<string, string>) => post("/personal/journal", j),
    mood: (m: Record<string, string>) => post("/personal/mood", m),
    expense: (e: Record<string, unknown>) => post("/personal/expenses", e),
    goal: (g: Record<string, unknown>) => post("/personal/goals", g),
    goalUpdate: (id: number, p: Record<string, unknown>) => patch(`/personal/goals/${id}`, p),
    habit: (name: string) => post("/personal/habits", { name }),
    habitDone: (id: number) => post(`/personal/habits/${id}/done`, {}),
    sleep: (s: Record<string, unknown>) => post("/personal/sleep", s),
  },
  memories: {
    list: (qs = "") => get<{ memories: Memory[]; stats: { total: number; by_domain: Record<string, number> } }>("/memories" + qs),
    create: (m: Partial<Memory>) => post<Memory>("/memories", m),
    search: (b: { query: string; domain?: string; limit?: number }) => post<{ results: Memory[] }>("/memories/search", b),
    update: (id: number, p: Partial<Memory>) => patch(`/memories/${id}`, p),
    remove: (id: number) => del(`/memories/${id}`),
    forget: (topic: string) => post<{ forgotten: number }>("/memories/forget", { topic }),
  },
  automations: {
    list: () => get<{ automations: Automation[] }>("/automations"),
    create: (a: Record<string, unknown>) => post("/automations", a),
    update: (id: number, p: Record<string, unknown>) => patch(`/automations/${id}`, p),
    run: (id: number, dry = false) => post(`/automations/${id}/run${dry ? "?dry_run=true" : ""}`, {}),
    dryRun: (id: number) => post<{ dry_run: boolean; automation: string; action_kind: string; fired: { ok: boolean; error?: string }; blocked: string[] }>(`/automations/${id}/run?dry_run=true`, {}),
    remove: (id: number) => del(`/automations/${id}`),
    missions: () => get<{ missions: Mission[] }>(`/missions`),
    planMission: (goal: string, planner = "auto") => post<{ id: number; goal: string; status: string; steps: MissionStep[]; needs_review: boolean; message: string; planner: string }>(`/missions`, { goal, planner }),
    controlMission: (id: number, action: string) => post<Mission>(`/missions/${id}/control`, { action }),
    scheduleMission: (id: number, every: string) => post<Mission>(`/missions/${id}/schedule`, { every }),
    missionRuns: (id: number) => get<{ runs: MissionRun[] }>(`/missions/${id}/runs`),
  },
  board: {
    get: () => get<{ columns: BoardColumn[]; counts: Record<string, number>; total: number; limit: number }>("/board"),
    move: (mission_id: number, column: string) =>
      post<{ ok: boolean; mission: BoardMission }>("/board/move", { mission_id, column }),
  },
  home: {
    status: () => get<HaStatus>(`/home/status`),
    entities: () => get<{ entities: HaEntity[]; mode: string; error?: string }>(`/home/entities`),
    service: (domain: string, service: string, entity_id = "", data?: Record<string, unknown>) => post<{ ok: boolean; mode?: string; state?: string; error?: string }>(`/home/service`, { domain, service, entity_id, data }),
  },
  undo: {
    preview: () => get<{ journal: UndoEntry[]; undoable: boolean }>("/undo"),
    apply: (steps = 1) => post<{ undone: { id: number; summary: string; result: string }[]; remaining: number }>("/undo", { steps }),
  },
  proactive: {
    list: (includeDismissed = false) => get<{ opportunities: Opportunity[] }>(`/proactive${includeDismissed ? "?include_dismissed=true" : ""}`),
    scan: () => post<{ opportunities: Opportunity[]; notified: string | null }>("/proactive/scan", {}),
    dismiss: (key: string, dismissed = true) => patch(`/proactive/${encodeURIComponent(key)}/dismiss`, { dismissed }),
    snooze: (key: string, hours = 24) => post(`/proactive/${encodeURIComponent(key)}/snooze`, { hours }),
    act: (key: string) => post<{ ok: boolean; kind?: string; action?: { kind: string; label?: string; view?: string; text?: string }; gone?: boolean; message?: string }>(`/proactive/${encodeURIComponent(key)}/act`, {}),
    resolved: () => get<{ resolved: { key: string; type: string; title: string; resolved_at: string }[] }>("/proactive/resolved"),
  },
  activity: (qs = "") => get<{ activity: Activity[] }>("/activity" + qs),
  notes: {
    list: () => get<{ notifications: Note[]; unread: number }>("/notifications"),
    read: (id: number) => post(`/notifications/${id}/read`, {}),
    readAll: () => post("/notifications/read-all", {}),
  },
  approvals: {
    list: () => get<{ approvals: { id: number; risk: string; title: string; status: string; created_at: string; detail: { drafts: { to: string; subject: string; body: string }[] } }[] }>("/approvals"),
    resolve: (id: number, decision: string, drafts?: { to: string; subject: string; body: string }[]) => post<{ decision: string; sent?: unknown[]; errors?: string[] }>(`/approvals/${id}/resolve`, { decision, drafts }),
  },
  gateway: {
    status: () => get<{ integrations: GwIntegration[]; events: GwEvent[] }>("/gateway/status"),
    connect: (p: string, body: { account?: string; mode?: string; config?: Record<string, string> }) => post<{ ok: boolean; mode: string }>(`/gateway/${p}/connect`, body),
    disconnect: (p: string, forget = false) => post(`/gateway/${p}/disconnect`, { forget }),
    test: (p: string) => post<{ ok: boolean; latency_ms: number; mode?: string; detail?: string; error?: string }>(`/gateway/${p}/test`, {}),
    simulate: (platform: string, text: string, extra?: { send_live?: boolean; to?: string }) => post<{ event_id: string; sent?: boolean; mode?: string }>(`/gateway/simulate`, { platform, text, ...extra }),
    telegramPoll: () => post<{ ok: boolean; fetched?: number; inbound?: { chat_id: string; text: string }[]; replies?: number; error?: string }>(`/gateway/telegram/poll`, {}),
  },
  files: {
    list: () => get<{ files: { id: number; name: string; mime: string; size: number; domain: string; created_at: string; analysis_count: number }[] }>("/files"),
    analyze: (id: number, question = "") => post<{ description: string; model: string; ms: number }>(`/files/${id}/analyze`, { question }),
    upload: async (fs: FileList, domain = "general") => {
      const fd = new FormData();
      Array.from(fs).forEach((f) => fd.append("files", f));
      fd.append("domain", domain);
      const res = await fetch(API + "/files/upload", { method: "POST", body: fd });
      if (!res.ok) throw new Error("upload failed");
      return res.json();
    },
  },
  vision: {
    status: () => get<{ ollama_model: string; ollama_online: boolean; cloud_configured: boolean; available: boolean }>("/vision/status"),
    look: async (blob: Blob, question = "", remember = true) => {
      const fd = new FormData();
      fd.append("frame", blob, "frame.jpg");
      fd.append("question", question);
      fd.append("remember", remember ? "1" : "0");
      const res = await fetch(API + "/vision/look", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text().catch(() => `look failed (${res.status})`));
      return res.json() as Promise<{ description: string; model: string; ms: number }>;
    },
  },
  backup: {
    run: () => post<{ ok: boolean; file?: string; size_bytes?: number; error?: string }>("/backup/run", {}),
    history: () => get<{ backups: { id: number; target: string; status: string; size_bytes: number; note: string; created_at: string }[]; files: { name: string; size_bytes: number; created_at: string }[] }>("/backup/history"),
    restore: (file: string) => post<{ ok: boolean; uploads_restored?: number; safety_copy?: string; error?: string }>("/backup/restore", { file }),
  },
  toolDryRun: (name: string, args: Record<string, unknown> = {}) => post<{ dry_run: boolean; tool: string; result?: unknown; error?: string; blocked: string[] }>(`/hermes/tools/${name}/dry-run`, { args, ctx: {} }),
  tools: () => get<{ tools: { name: string; risk: string; description: string; category: string }[]; hermes: string }>("/tools"),
  sessions: {
    list: (q = "") => get<{ sessions: Session[] }>(`/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    get: (sid: string) => get<{ messages: { role: string; content: string }[] }>(`/sessions/${sid}`),
    create: (title = "Conversation", domain = "general") => post<{ id: string }>("/sessions", { title, domain }),
    update: (sid: string, p: Record<string, unknown>) => patch(`/sessions/${sid}`, p),
    remove: (sid: string) => del(`/sessions/${sid}`),
    branch: (sid: string, title = "") => post<{ id: string }>(`/sessions/${sid}/branch`, { title }),
    pin: (sid: string, pinned?: boolean) => post<{ pinned: boolean }>(`/sessions/${sid}/pin`, pinned === undefined ? {} : { pinned }),
    star: (sid: string, starred?: boolean) => post<{ starred: boolean }>(`/sessions/${sid}/star`, starred === undefined ? {} : { starred }),
    compact: (sid: string) => post<{ compacted: boolean; summary?: string; chunk?: number }>(`/sessions/${sid}/compact`, {}),
  },
  voice: {
    config: () => get<{ stt: string; tts: string; language: string; note: string }>("/voice/config"),
    log: (transcript: string) => post("/voice/log", { transcript }),
    status: () => get<{ stt_installed: boolean; tts_installed: boolean; whisper_model: string; whisper_ready: boolean; piper_voice: string; piper_ready: boolean; note: string }>("/voice/status"),
    transcribe: async (blob: Blob) => {
      const fd = new FormData();
      fd.append("audio", blob, "clip.webm");
      const res = await fetch(API + "/voice/transcribe", { method: "POST", body: fd });
      if (!res.ok) throw new Error(`transcribe failed (${res.status})`);
      return res.json() as Promise<{ text: string; language: string; duration: number }>;
    },
    engines: () => get<{ engines: { id: string; label: string; offline: boolean; available: boolean; voices?: { id: string; label: string }[]; features: string[]; note: string }[]; emotions: { id: string; label: string }[]; current: Record<string, unknown> }>("/voice/engines"),
    speakUrl: async (text: string, opts: { engine?: string; voice?: string; emotion?: string } = {}, signal?: AbortSignal) => {
      const res = await fetch(API + "/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, ...opts }), signal });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(detail || `TTS failed (${res.status})`);
      }
      const blob = await res.blob();
      signal?.throwIfAborted();
      return URL.createObjectURL(blob);
    },
    loopStatus: () => get<{ wake_available: boolean; wake_model: string; wake_enabled: boolean; whisper: boolean; tts: Record<string, unknown>; ws: string }>("/voice/loop/status"),
    loopWsUrl: () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/voice/loop`,
  },
  settings: {
    get: () => get<{ values: Record<string, unknown>; secrets: Record<string, boolean>; sources: Record<string, string> }>("/settings"),
    update: (b: Record<string, unknown>) => patch<{ values: Record<string, unknown>; secrets: Record<string, boolean>; sources: Record<string, string> }>("/settings", b),
    reset: () => del<{ values: Record<string, unknown>; secrets: Record<string, boolean>; sources: Record<string, string> }>("/settings"),
  },
  cloud: {
    models: (refresh = false) => get<{ models: { id: string; name: string; context_length: number; free: boolean; reasoning?: boolean; vision?: boolean; multimodal?: boolean; modality?: string }[]; cached: boolean; stale: boolean; count: number; error?: string; note?: string }>(`/cloud/models${refresh ? "?refresh=true" : ""}`),
    test: (b: { provider?: string; model?: string; api_key?: string }) => post<{ ok: boolean; latency_ms?: number; model: string; provider: string; reply?: string; error?: string }>("/cloud/test", b),
  },
  brief: {
    list: () => get<{ briefings: Briefing[] }>("/briefings"),
    create: (b: Record<string, unknown>) => post("/briefings", b),
    update: (id: number, p: Record<string, unknown>) => patch(`/briefings/${id}`, p),
    remove: (id: number) => del(`/briefings/${id}`),
    run: (id: number, extra = "") => post<{ run_id: number; kind: string; model: string; ms: number; output: string }>(`/briefings/${id}/run`, { extra }),
    runNow: (kind = "morning", extra = "") => post<{ run_id: number; kind: string; model: string; ms: number; output: string }>("/briefings/run-now", { kind, extra }),
    runs: (bid?: number) => get<{ runs: BriefRun[] }>(`/briefings/runs/list${bid ? `?briefing_id=${bid}` : ""}`),
  },
  mail: {
    accounts: () => get<{ accounts: MailAccount[] }>("/mail/accounts"),
    createAccount: (b: Record<string, unknown>) => post("/mail/accounts", b),
    updateAccount: (id: number, p: Record<string, unknown>) => patch(`/mail/accounts/${id}`, p),
    removeAccount: (id: number) => del(`/mail/accounts/${id}`),
    sync: (id: number) => post<{ ok: boolean; mode: string; new: number; error?: string }>(`/mail/accounts/${id}/sync`, {}),
    emails: (qs = "") => get<{ emails: Mail[]; unread: number }>("/mail/emails" + qs),
    get: (id: number) => get<MailFull>(`/mail/emails/${id}`),
    set: (id: number, b: Record<string, unknown>) => patch(`/mail/emails/${id}`, b),
    triage: (b?: Record<string, unknown>) => post<{ triaged: number; llm_used: number; checked: number }>("/mail/triage", b || {}),
  },
  cal: {
    list: () => get<{ calendars: Cal[] }>("/calendar/calendars"),
    create: (b: Record<string, unknown>) => post("/calendar/calendars", b),
    update: (id: number, p: Record<string, unknown>) => patch(`/calendar/calendars/${id}`, p),
    remove: (id: number) => del(`/calendar/calendars/${id}`),
    sync: (id: number) => post<{ ok: boolean; source: string; new?: number; updated?: number; error?: string }>(`/calendar/calendars/${id}/sync`, {}),
    events: (start: string, end: string) => get<{ events: CalEvent[] }>(`/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
    today: () => get<{ events: CalEvent[] }>("/calendar/today"),
    week: () => get<{ events: CalEvent[] }>("/calendar/week"),
    createEvent: (b: Record<string, unknown>) => post("/calendar/events", b),
    updateEvent: (id: number, p: Record<string, unknown>) => patch(`/calendar/events/${id}`, p),
    deleteEvent: (id: number) => del(`/calendar/events/${id}`),
    googleAuthUrl: (cid: number, redirect: string) => get<{ url: string }>(`/calendar/google/auth-url?calendar_id=${cid}&redirect_uri=${encodeURIComponent(redirect)}`),
    googleCallback: (b: Record<string, unknown>) => post("/calendar/google/callback", b),
  },
  sync: {
    export: (device = "") => get(`/sync/export?device=${encodeURIComponent(device)}`),
    import: (bundle: unknown, device: string) => post<{ tables: Record<string, { inserted: number; skipped: number; conflicts: number }>; conflicts: unknown[]; inserted: number }>("/sync/import", { bundle, device }),
    log: () => get<{ log: { id: number; device: string; direction: string; conflicts: number; note: string; created_at: string }[] }>("/sync/log"),
  },
  push: {
    vapidKey: () => get<{ key: string | null; configured: boolean }>("/push/vapid-public-key"),
    subscribe: (s: { endpoint?: string; keys?: { p256dh?: string; auth?: string } }) => post("/push/subscribe", s),
    unsubscribe: (endpoint: string) => post("/push/unsubscribe", { endpoint }),
    test: (t: Record<string, string>) => post("/push/test", t),
  },
  /* ---- v1.14 machine room ---- */
  ollama: {
    status: () => get<{ reachable: boolean; base_url: string; model_count: number; synced_at: string; stale: boolean;
      error: string; chat_model: string; vision_model: string; embed_model: string; auto_sync: boolean }>("/ollama/status"),
    models: () => get<{ reachable: boolean; base_url: string; error?: string; models: OllamaModel[] }>("/ollama/models"),
    sync: () => post<{ ok: boolean; models?: number; names?: string[]; synced_at?: string; base_url?: string; error?: string }>("/ollama/sync", {}),
    setDefault: (role: string, model: string) => post<{ ok: boolean; role: string; model: string }>("/ollama/default", { role, model }),
  },
  terminal: {
    config: () => get<{ enabled: boolean; cwd: string; timeout_s: number; max_out_kb: number; allow_dangerous: boolean }>("/terminal/config"),
    exec: (command: string, machine = "local", timeout?: number) =>
      post<TermRun & { output?: string; cwd?: string; risk?: string; denied?: boolean; dry_run?: boolean; truncated?: boolean; error?: string }>(
        "/terminal/exec", { command, machine, ...(timeout ? { timeout } : {}) }),
    history: (limit = 50) => get<{ runs: TermRunRow[] }>(`/terminal/history?limit=${limit}`),
    machines: () => get<{ machines: MachineInfo[]; ssh_available: boolean }>("/terminal/machines"),
    saveMachines: (machines: { name: string; host: string }[]) => put<{ ok: boolean; machines: MachineInfo[] }>("/terminal/machines", { machines }),
    setCwd: (cwd: string) => patch<{ ok: boolean; cwd?: string }>("/terminal/config", { cwd }),
  },
  feeds: {
    list: () => get<{ feeds: Feed[]; items: FeedItem[] }>("/feeds"),
    add: (url: string) => post<{ id: number; title?: string; items?: number; already_existed?: boolean }>("/feeds", { url }),
    remove: (id: number) => del(`/feeds/${id}`),
    refresh: () => post<{ feeds: number; new_items: number; errors: number }>("/feeds/refresh", {}),
    read: (id: number, read = true) => post(`/feeds/items/${id}/read`, { read }),
  },
  weather: {
    now: (refresh = false) => get<Weather>("/weather" + (refresh ? "?refresh=true" : "")),
  },
  calls: {
    save: (b: { transcript: string; mode: string; started_at: string; ended_at: string; seconds?: number }) =>
      post<{ ok: boolean; id: number; summary: string; model: string; call: VoiceCall }>("/voice/calls", b),
    list: (limit = 20) => get<{ calls: VoiceCall[] }>(`/voice/calls?limit=${limit}`),
    get: (id: number) => get<VoiceCall & { transcript: string; turns_list: string[] }>(`/voice/calls/${id}`),
    remove: (id: number) => del(`/voice/calls/${id}`),
  },
  /* ---- v1.15 fortress layer ---- */
  scripts: {
    list: () => get<{ scripts: SavedScript[] }>("/scripts"),
    save: (s: { name: string; command: string; machine?: string; description?: string }) =>
      post<{ ok: boolean; id: number; name: string; risk: string }>("/scripts", s),
    remove: (id: number) => del(`/scripts/${id}`),
    run: (id: number, args?: Record<string, string>) =>
      post<TermRun & { ok: boolean; output?: string; script?: string; denied?: boolean; error?: string; cwd?: string; risk?: string }>(`/scripts/${id}/run`, args ? { args } : {}),
  },
  watch: {
    state: () => get<WatchState>("/watch"),
    setPaths: (paths: string[]) => put<{ ok: boolean; paths: string[] }>("/watch/paths", { paths }),
    scan: () => post<{ new: number; changed: number; skipped_ext: number; errors: number }>("/watch/scan", {}),
    reset: () => post<{ ok: boolean; cleared: number }>("/watch/reset", {}),
  },
  machineCheck: (name: string) => get<MachineCheck>(`/terminal/check?machine=${encodeURIComponent(name)}`),
};

export interface SavedScript {
  id: number; name: string; command: string; machine: string; description: string;
  run_count: number; last_run: string; last_status: string; created_at: string;
}
export interface WatchState {
  enabled: boolean; ingest: boolean; paths: string[]; interval_s: number; default_dir: string;
  recent: { path: string; size: number; mtime: number; file_id: number | null; ingested: number; last_event: string }[];
}
export interface MachineCheck {
  machine: string; ok: boolean; ms?: number; host?: string; port?: number; detail?: string; error?: string; kind?: string;
}

export interface OllamaModel {
  name: string; family: string; size_bytes: number; size: string;
  parameter_size: string; quantization: string; modified_at: string;
  capabilities: string[]; synced_at: string; note?: string;
}
export interface TermRun { exit_code: number | null; duration_ms: number; machine: string }
export interface TermRunRow {
  id: number; created_at: string; source: string; machine: string; command: string; cwd: string;
  exit_code: number | null; duration_ms: number; out_kb: number; risk: string; status: string; note: string;
}
export interface MachineInfo { name: string; host: string; kind: string; ssh_ready?: boolean }
export interface Feed { id: number; url: string; title: string; last_fetched: string; error: string; n_items: number; n_unread: number }
export interface FeedItem {
  id: number; feed_id: number; guid: string; title: string; link: string;
  published: string; fetched_at: string; read: number; feed_title?: string; feed_url?: string;
}
export interface Weather {
  ok: boolean; reason?: string; configured?: boolean; enabled?: boolean; place?: string;
  temp_c?: number; feels_c?: number; humidity_pct?: number; wind_kmh?: number;
  condition?: string; cached?: boolean;
  today?: { date: string; high_c: number | null; low_c: number | null; rain_pct: number | null; condition: string }[];
}
export interface VoiceCall {
  id: number; started_at: string; ended_at: string; mode: string; seconds: number;
  turns: number; summary: string; model: string; source: string; transcript?: string;
}
export type BoardMission = { id: number; goal: string; status: string; steps_total: number; steps_done: number; next_run_at: string; created_at: string; updated_at: string };
export type BoardColumn = { key: "backlog" | "running" | "awaiting" | "done"; label: string; missions: BoardMission[] };

/* tiny markdown: bold, italic, code, bullets, numbered, quotes, headings */
export function md(src: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = src.split("\n");
  let html = "", inUl = false, inOl = false;
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*([^*"]+)\*/g, "<em>$1</em>");
  const close = () => { if (inUl) { html += "</ul>"; inUl = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  for (const ln of lines) {
    const t = ln.trim();
    if (/^#{1,3} /.test(t)) { close(); html += `<div class="mdh">${inline(t.replace(/^#+ /, ""))}</div>`; }
    else if (/^> /.test(t)) { close(); html += `<blockquote>${inline(t.slice(2))}</blockquote>`; }
    else if (/^[-•] /.test(t)) { if (!inUl) { close(); html += "<ul>"; inUl = true; } html += `<li>${inline(t.slice(2))}</li>`; }
    else if (/^\d+\. /.test(t)) { if (!inOl) { close(); html += "<ol>"; inOl = true; } html += `<li>${inline(t.replace(/^\d+\. /, ""))}</li>`; }
    else if (t === "") { close(); }
    else { close(); html += `<p>${inline(t)}</p>`; }
  }
  close();
  return html;
}

export const ago = (iso: string | null) => {
  if (!iso) return "—";
  const s = Math.max(1, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

export const uid = () => Math.random().toString(36).slice(2, 10);
