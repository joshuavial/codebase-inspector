loadConcepts({
 "workspace": "orchestra",
 "summary": "A read-only desktop and phone overview of JV's orchestrator and lead agents: what needs him, quota, delegations and lead cards.",
 "concepts": [
  {
   "id": "desktop",
   "name": "Desktop app",
   "summary": "The Electron main process: window, IPC to the overview UI, terminal jumps and task summaries.",
   "children": [
    {
     "id": "desktop.shell",
     "name": "Window and IPC bridge",
     "summary": "Opens the window, starts the poller and exposes a read-only API to the UI.",
     "files": [
      "electron/main.ts",
      "electron/preload.ts",
      "src/types/preload.d.ts"
     ],
     "tests": [],
     "symbols": [
      {
       "id": "local:orchestra:electron/main.ts#boundsPath",
       "name": "boundsPath",
       "kind": "function",
       "sig": "function boundsPath(): string",
       "file": "electron/main.ts",
       "line": 25,
       "concept": "desktop.shell",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/main.ts#readBounds",
       "name": "readBounds",
       "kind": "function",
       "sig": "function readBounds(): WindowBounds | null",
       "file": "electron/main.ts",
       "line": 29,
       "concept": "desktop.shell",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/main.ts#visibleBounds",
       "name": "visibleBounds",
       "kind": "function",
       "sig": "function visibleBounds(saved: WindowBounds | null): Electron.Rectangle",
       "file": "electron/main.ts",
       "line": 42,
       "concept": "desktop.shell",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/main.ts#loopbackUrl",
       "name": "loopbackUrl",
       "kind": "function",
       "sig": "function loopbackUrl(raw: string | undefined): string | null",
       "file": "electron/main.ts",
       "line": 68,
       "concept": "desktop.shell",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/main.ts#createWindow",
       "name": "createWindow",
       "kind": "function",
       "sig": "function createWindow()",
       "file": "electron/main.ts",
       "line": 80,
       "concept": "desktop.shell",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:electron/main.ts#createWindow",
       "local:orchestra:electron/main.ts#boundsPath"
      ],
      [
       "local:orchestra:electron/main.ts#createWindow",
       "local:orchestra:electron/main.ts#loopbackUrl"
      ],
      [
       "local:orchestra:electron/main.ts#createWindow",
       "local:orchestra:electron/main.ts#readBounds"
      ],
      [
       "local:orchestra:electron/main.ts#createWindow",
       "local:orchestra:electron/main.ts#visibleBounds"
      ],
      [
       "local:orchestra:electron/main.ts#readBounds",
       "local:orchestra:electron/main.ts#boundsPath"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "desktop.goto",
     "name": "Go to terminal",
     "summary": "Selects a lead's tmux pane and focuses or opens its iTerm2 tab, rate limited.",
     "files": [
      "electron/goto.ts"
     ],
     "tests": [
      {
       "file": "electron/goto.test.ts",
       "cases": 9
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:electron/goto.ts#resolveTmux",
       "name": "resolveTmux",
       "kind": "function",
       "sig": "function resolveTmux(): string",
       "file": "electron/goto.ts",
       "line": 29,
       "concept": "desktop.goto",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/goto.ts#gotoTarget",
       "name": "gotoTarget",
       "kind": "function",
       "sig": "function gotoTarget(snapshot: Snapshot, registry: unknown, req: unknown): GotoTarget | \"unknown\" | \"no-target\"",
       "file": "electron/goto.ts",
       "line": 35,
       "concept": "desktop.goto",
       "tests": [
        "lookup uses the current snapshot and rejects unknown leads and lanes"
       ]
      },
      {
       "id": "local:orchestra:electron/goto.ts#asString",
       "name": "asString",
       "kind": "function",
       "sig": "const asString = (s: string) =>",
       "file": "electron/goto.ts",
       "line": 51,
       "concept": "desktop.goto",
       "tests": [
        "AppleScript escaping"
       ]
      },
      {
       "id": "local:orchestra:electron/goto.ts#focusScript",
       "name": "focusScript",
       "kind": "function",
       "sig": "function focusScript(tty: string): string",
       "file": "electron/goto.ts",
       "line": 53,
       "concept": "desktop.goto",
       "tests": [
        "focused: most recently active client on the session, exact argv"
       ]
      },
      {
       "id": "local:orchestra:electron/goto.ts#openScript",
       "name": "openScript",
       "kind": "function",
       "sig": "function openScript(command: string): string",
       "file": "electron/goto.ts",
       "line": 72,
       "concept": "desktop.goto",
       "tests": [
        "opened: no client on the session (others ignored), never switch-client",
        "opened with a socket attaches through it",
        "AppleScript escaping"
       ]
      },
      {
       "id": "local:orchestra:electron/goto.ts#gotoTerminal",
       "name": "gotoTerminal",
       "kind": "function",
       "sig": "async function gotoTerminal(t: GotoTarget, exec: Exec, tmuxBin: string): Promise<GotoResult>",
       "file": "electron/goto.ts",
       "line": 83,
       "concept": "desktop.goto",
       "tests": [
        "invalid target or socket runs nothing",
        "focused: most recently active client on the session, exact argv",
        "opened: no client on the session (others ignored), never switch-client",
        "opened with a socket attaches through it",
        "failures are short classes"
       ]
      },
      {
       "id": "local:orchestra:electron/goto.ts#rateLimit",
       "name": "rateLimit",
       "kind": "function",
       "sig": "function rateLimit(ms: number): (now: number) => boolean",
       "file": "electron/goto.ts",
       "line": 117,
       "concept": "desktop.goto",
       "tests": [
        "rate limit: one call per 500 ms"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:electron/goto.ts#focusScript",
       "local:orchestra:electron/goto.ts#asString"
      ],
      [
       "local:orchestra:electron/goto.ts#gotoTerminal",
       "local:orchestra:electron/goto.ts#focusScript"
      ],
      [
       "local:orchestra:electron/goto.ts#gotoTerminal",
       "local:orchestra:electron/goto.ts#openScript"
      ],
      [
       "local:orchestra:electron/goto.ts#openScript",
       "local:orchestra:electron/goto.ts#asString"
      ]
     ],
     "callsOut": [
      "core.runtime"
     ]
    },
    {
     "id": "desktop.summaries",
     "name": "Task summaries",
     "summary": "One-line cheap-model summaries of background tasks and CLI calls.",
     "files": [
      "electron/summarizer.ts"
     ],
     "tests": [
      {
       "file": "electron/summarizer.test.ts",
       "cases": 19
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:electron/summarizer.ts#realSummaryExec",
       "name": "realSummaryExec",
       "kind": "function",
       "sig": "const realSummaryExec: SummaryExec = (file, args, o) =>",
       "file": "electron/summarizer.ts",
       "line": 14,
       "concept": "desktop.summaries",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#filterForModel",
       "name": "filterForModel",
       "kind": "function",
       "sig": "function filterForModel(text: string): string",
       "file": "electron/summarizer.ts",
       "line": 78,
       "concept": "desktop.summaries",
       "tests": [
        "filter: scrubs tokens",
        "filter: drops env assignments, exported or not",
        "filter: drops lines containing ${word}",
        "filter: a long one-line prompt loses only the sentence naming a credential",
        "filter: drops PEM blocks, including an unterminated one"
       ]
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#denied",
       "name": "denied",
       "kind": "function",
       "sig": "const denied = (p: string, home: string) =>",
       "file": "electron/summarizer.ts",
       "line": 87,
       "concept": "desktop.summaries",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#readableFile",
       "name": "readableFile",
       "kind": "function",
       "sig": "function readableFile(p: string, home = HOME): boolean",
       "file": "electron/summarizer.ts",
       "line": 98,
       "concept": "desktop.summaries",
       "tests": [
        "files: credential names and stores are never read"
       ]
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#readSlice",
       "name": "readSlice",
       "kind": "function",
       "sig": "function readSlice(p: string, bytes: number, from: \"head\" | \"tail\", home: string): string",
       "file": "electron/summarizer.ts",
       "line": 108,
       "concept": "desktop.summaries",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#fileSize",
       "name": "fileSize",
       "kind": "function",
       "sig": "const fileSize = (p: string | null) =>",
       "file": "electron/summarizer.ts",
       "line": 122,
       "concept": "desktop.summaries",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#promptFile",
       "name": "promptFile",
       "kind": "function",
       "sig": "function promptFile(argv: string, stdinLsof: string): string | null",
       "file": "electron/summarizer.ts",
       "line": 131,
       "concept": "desktop.summaries",
       "tests": [
        "prompt file: stdin regular file, else --prompt-file, else -o"
       ]
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#taskWhy",
       "name": "taskWhy",
       "kind": "function",
       "sig": "function taskWhy(log: string, pid: number): string | null",
       "file": "electron/summarizer.ts",
       "line": 141,
       "concept": "desktop.summaries",
       "tests": []
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#createSummarizer",
       "name": "createSummarizer",
       "kind": "function",
       "sig": "function createSummarizer(opts: SummarizerOptions)",
       "file": "electron/summarizer.ts",
       "line": 171,
       "concept": "desktop.summaries",
       "tests": [
        "summarizer.test.ts"
       ]
      },
      {
       "id": "local:orchestra:electron/summarizer.ts#summaryItems",
       "name": "summaryItems",
       "kind": "function",
       "sig": "function summaryItems(snapshot: Snapshot, processes: unknown): SummaryItem[]",
       "file": "electron/summarizer.ts",
       "line": 301,
       "concept": "desktop.summaries",
       "tests": [
        "summary items: every task and CLI call on screen, orchestrator first, with main-only detail and output path"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:electron/summarizer.ts#createSummarizer",
       "local:orchestra:electron/summarizer.ts#fileSize"
      ],
      [
       "local:orchestra:electron/summarizer.ts#createSummarizer",
       "local:orchestra:electron/summarizer.ts#filterForModel"
      ],
      [
       "local:orchestra:electron/summarizer.ts#createSummarizer",
       "local:orchestra:electron/summarizer.ts#promptFile"
      ],
      [
       "local:orchestra:electron/summarizer.ts#createSummarizer",
       "local:orchestra:electron/summarizer.ts#readSlice"
      ],
      [
       "local:orchestra:electron/summarizer.ts#createSummarizer",
       "local:orchestra:electron/summarizer.ts#taskWhy"
      ],
      [
       "local:orchestra:electron/summarizer.ts#readSlice",
       "local:orchestra:electron/summarizer.ts#readableFile"
      ],
      [
       "local:orchestra:electron/summarizer.ts#readableFile",
       "local:orchestra:electron/summarizer.ts#denied"
      ]
     ],
     "callsOut": [
      "core.runtime",
      "core.safety"
     ]
    },
    {
     "id": "desktop.messages",
     "name": "Message actions",
     "summary": "Show, reply, archive and jump from operator messages, resolving the sender's terminal.",
     "files": [
      "electron/messages.ts"
     ],
     "tests": [
      {
       "file": "electron/messages.test.ts",
       "cases": 7
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:electron/messages.ts#showMessage",
       "name": "showMessage",
       "kind": "function",
       "sig": "const showMessage = (snapshot: Snapshot, id: unknown, exec: MessageExec) =>",
       "file": "electron/messages.ts",
       "line": 18,
       "concept": "desktop.messages",
       "tests": [
        "show, reply, and archive validate current ids and use fixed msg argv"
       ]
      },
      {
       "id": "local:orchestra:electron/messages.ts#peekMessage",
       "name": "peekMessage",
       "kind": "function",
       "sig": "const peekMessage = (snapshot: Snapshot, id: unknown, exec: MessageExec) =>",
       "file": "electron/messages.ts",
       "line": 19,
       "concept": "desktop.messages",
       "tests": [
        "bounded direct-core and Electron message detail remain byte-equivalent",
        "peek detail uses fixed read-only argv, current ids only, and parses the schema-v1 peek contract"
       ]
      },
      {
       "id": "local:orchestra:electron/messages.ts#replyMessage",
       "name": "replyMessage",
       "kind": "function",
       "sig": "const replyMessage = (snapshot: Snapshot, id: unknown, body: unknown, exec: MessageExec) =>",
       "file": "electron/messages.ts",
       "line": 20,
       "concept": "desktop.messages",
       "tests": [
        "show, reply, and archive validate current ids and use fixed msg argv"
       ]
      },
      {
       "id": "local:orchestra:electron/messages.ts#archiveMessage",
       "name": "archiveMessage",
       "kind": "function",
       "sig": "const archiveMessage = (snapshot: Snapshot, id: unknown, exec: MessageExec) =>",
       "file": "electron/messages.ts",
       "line": 21,
       "concept": "desktop.messages",
       "tests": [
        "show, reply, and archive validate current ids and use fixed msg argv"
       ]
      },
      {
       "id": "local:orchestra:electron/messages.ts#messageGotoTarget",
       "name": "messageGotoTarget",
       "kind": "function",
       "sig": "function messageGotoTarget(snapshot: Snapshot, messages: unknown, registry: unknown, id: unknown): GotoTarget | \"unknown\" | \"no-target\"",
       "file": "electron/messages.ts",
       "line": 24,
       "concept": "desktop.messages",
       "tests": [
        "links and go-to targets must belong to a current thread"
       ]
      }
     ],
     "calls": [],
     "callsOut": []
    },
    {
     "id": "desktop.adapters",
     "name": "Core adapters",
     "summary": "Thin re-exports that keep the desktop module API stable over the shared core.",
     "files": [
      "electron/env.ts",
      "electron/sources.ts",
      "electron/poller.ts",
      "electron/sanitize.ts",
      "electron/snapshot.ts",
      "electron/mobile.ts"
     ],
     "tests": [
      {
       "file": "electron/core-equivalence.test.ts",
       "cases": 13
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:electron/poller.ts#startPoller",
       "name": "startPoller",
       "kind": "function",
       "sig": "function startPoller( sources: Source[], opts: { exec?: ExecFn; onChange: (name: SourceName) => void; log?: (line: string) => void; shouldRun?: () => boolean; runtime?: PollerRuntime }, )",
       "file": "electron/poller.ts",
       "line": 11,
       "concept": "desktop.adapters",
       "tests": [
        "first runs are staggered by offset, then repeat at the interval",
        "a run still going skips its next tick",
        "timeout aborts the child and records 'timeout'",
        "errors are classified: non-zero exit, ENOENT, bad JSON",
        "last good data is kept on failure and replaced on recovery",
        "no second run starts while a timed-out child has not exited",
        "stop() aborts in-flight children and stops scheduling"
       ]
      },
      {
       "id": "local:orchestra:electron/snapshot.ts#taskRunOutputPath",
       "name": "taskRunOutputPath",
       "kind": "function",
       "sig": "const taskRunOutputPath = (snapshot: Snapshot, tasks: unknown, id: unknown) =>",
       "file": "electron/snapshot.ts",
       "line": 6,
       "concept": "desktop.adapters",
       "tests": [
        "taskRun:reveal lookup: only a finished run in the snapshot with a revealable output path"
       ]
      },
      {
       "id": "local:orchestra:electron/sources.ts#readTail",
       "name": "readTail",
       "kind": "function",
       "sig": "const readTail = (file: string, maxBytes = TASKS_TAIL_BYTES) =>",
       "file": "electron/sources.ts",
       "line": 18,
       "concept": "desktop.adapters",
       "tests": [
        "tasks tail: last N bytes from a whole line; the whole file when small"
       ]
      },
      {
       "id": "local:orchestra:electron/sources.ts#parseProcesses",
       "name": "parseProcesses",
       "kind": "function",
       "sig": "const parseProcesses = (stdout: string, now = Date.now(), appPid = process.pid) =>",
       "file": "electron/sources.ts",
       "line": 19,
       "concept": "desktop.adapters",
       "tests": [
        "task:reveal lookup: only a pid in the snapshot with a TASK_OUTPUT file",
        "selected ps command lines are truncated to 4 KB before task parsing",
        "processes: table is allowlisted, scrubbed, single-line and 120 chars; startedAt from etime",
        "live CLI observations retain only pid, age, safe tool and main-only attribution path",
        "processes: the Orchestra app process tree is excluded from tasks and lane activity",
        "processes: kinds come from the batched lsof fd 1 rows"
       ]
      },
      {
       "id": "local:orchestra:electron/sources.ts#parseTasks",
       "name": "parseTasks",
       "kind": "function",
       "sig": "const parseTasks = (stdout: string) =>",
       "file": "electron/sources.ts",
       "line": 20,
       "concept": "desktop.adapters",
       "tests": [
        "tasks fold: 24 h window, done, failed, retry keeps the latest start, running vs lost by pid, end-only dropped",
        "tasks allowlist: only the contract fields, scrubbed and truncated; output kept as a revealable path and its basename"
       ]
      },
      {
       "id": "local:orchestra:electron/sources.ts#revealablePath",
       "name": "revealablePath",
       "kind": "function",
       "sig": "const revealablePath = (value: unknown, home = HOME) =>",
       "file": "electron/sources.ts",
       "line": 21,
       "concept": "desktop.adapters",
       "tests": [
        "Electron source compatibility defaults retain HOME-scoped output paths",
        "tasks reveal path: absolute, normalised, under home or /private/tmp, not token-shaped"
       ]
      },
      {
       "id": "local:orchestra:electron/sources.ts#foldTasks",
       "name": "foldTasks",
       "kind": "function",
       "sig": "const foldTasks = (rows: unknown[], now: number, alive: Set<number>, home = HOME) =>",
       "file": "electron/sources.ts",
       "line": 22,
       "concept": "desktop.adapters",
       "tests": [
        "Electron source compatibility defaults retain HOME-scoped output paths",
        "tasks fold: 24 h window, done, failed, retry keeps the latest start, running vs lost by pid, end-only dropped",
        "tasks retain scrubbed, capped cwd and ancestry internally for unattributed-run diagnosis"
       ]
      }
     ],
     "calls": [],
     "callsOut": [
      "core.poller",
      "core.runtime",
      "core.snapshot",
      "core.sources"
     ]
    }
   ]
  },
  {
   "id": "ui",
   "name": "Lead overview UI",
   "summary": "The React window that shows what needs JV, lead cards, the orchestrator board, messages and quota.",
   "children": [
    {
     "id": "ui.app",
     "name": "App shell",
     "summary": "Mounts the app, subscribes to snapshots and lays out the panels.",
     "files": [
      "src/main.tsx",
      "src/App.tsx",
      "vite.config.ts"
     ],
     "tests": [
      {
       "file": "src/styles.test.ts",
       "cases": 7
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/App.tsx#App",
       "name": "App",
       "kind": "component",
       "sig": "function App()",
       "file": "src/App.tsx",
       "line": 13,
       "concept": "ui.app",
       "tests": []
      },
      {
       "id": "local:orchestra:vite.config.ts#cspPlugin",
       "name": "cspPlugin",
       "kind": "function",
       "sig": "function cspPlugin(): Plugin",
       "file": "vite.config.ts",
       "line": 7,
       "concept": "ui.app",
       "tests": []
      }
     ],
     "calls": [],
     "callsOut": [
      "ui.board",
      "ui.leads",
      "ui.messages",
      "ui.quota",
      "ui.viewmodel"
     ]
    },
    {
     "id": "ui.leads",
     "name": "Lead cards",
     "summary": "Per-lead cards and summaries with their lanes, subagents and background tasks.",
     "files": [
      "src/components/LeadCard.tsx",
      "src/components/LeadSummary.tsx",
      "src/components/BackgroundTasks.tsx"
     ],
     "tests": [
      {
       "file": "src/components/LeadCard.test.ts",
       "cases": 5
      },
      {
       "file": "src/components/LeadSummary.test.ts",
       "cases": 1
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#Label",
       "name": "Label",
       "kind": "component",
       "sig": "function Label({ summary, fallback }: { summary: string | null; fallback: string })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 7,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#CliRow",
       "name": "CliRow",
       "kind": "component",
       "sig": "function CliRow({ call, now }: { call: CliCall; now: number })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 12,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#TaskRow",
       "name": "TaskRow",
       "kind": "component",
       "sig": "function TaskRow({ task, now }: { task: BackgroundTask; now: number })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 22,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#LeadTasks",
       "name": "LeadTasks",
       "kind": "component",
       "sig": "function LeadTasks({ tasks, cliCalls, counts, now, panel }: { tasks: BackgroundTask[]; cliCalls: CliCall[]; counts: string; now: number; panel: string })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 36,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#RunRow",
       "name": "RunRow",
       "kind": "component",
       "sig": "function RunRow({ run, now }: { run: TaskRun; now: number })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 47,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#MoreRuns",
       "name": "MoreRuns",
       "kind": "component",
       "sig": "function MoreRuns({ group }: { group: TaskHistoryGroup })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 65,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#RunList",
       "name": "RunList",
       "kind": "component",
       "sig": "function RunList({ title, group, status, now, panel }: { title: string; group: TaskHistoryGroup; status: \"done\" | \"failed\"; now: number; panel: string })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 73,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#TaskHistoryLists",
       "name": "TaskHistoryLists",
       "kind": "component",
       "sig": "function TaskHistoryLists({ group, now, panel }: { group: TaskHistoryGroup; now: number; panel: string })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 83,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#UnattributedRunRow",
       "name": "UnattributedRunRow",
       "kind": "component",
       "sig": "function UnattributedRunRow({ run, now }: { run: UnattributedTaskRun; now: number })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 92,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/BackgroundTasks.tsx#UnattributedTaskDetails",
       "name": "UnattributedTaskDetails",
       "kind": "component",
       "sig": "function UnattributedTaskDetails({ group, now }: { group: UnattributedTaskHistoryGroup; now: number })",
       "file": "src/components/BackgroundTasks.tsx",
       "line": 101,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#GotoButton",
       "name": "GotoButton",
       "kind": "component",
       "sig": "function GotoButton({ leadId, lane, target, label, className = \"goto\" }: { leadId: string; lane?: string; target: string | null; label: string; className?: string })",
       "file": "src/components/LeadCard.tsx",
       "line": 11,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#PrLink",
       "name": "PrLink",
       "kind": "component",
       "sig": "function PrLink({ pr, label, className }: { pr: PullRequest; label: string; className: string })",
       "file": "src/components/LeadCard.tsx",
       "line": 26,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#etaText",
       "name": "etaText",
       "kind": "function",
       "sig": "function etaText(eta: number, now: number): string",
       "file": "src/components/LeadCard.tsx",
       "line": 30,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#MissionView",
       "name": "MissionView",
       "kind": "component",
       "sig": "function MissionView({ mission, now, compact = false, unavailable = false }: { mission: Mission; now: number; compact?: boolean; unavailable?: boolean })",
       "file": "src/components/LeadCard.tsx",
       "line": 35,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "name": "LeadCard",
       "kind": "component",
       "sig": "function LeadCard({ lead, now }: { lead: Lead; now: number })",
       "file": "src/components/LeadCard.tsx",
       "line": 70,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadCard.tsx#LeadList",
       "name": "LeadList",
       "kind": "component",
       "sig": "function LeadList({ leads, statuses, now, selectedId, showAll, onToggleAll }: { leads: Lead[]; statuses: SourceStatus[]; now: number; selectedId: string | null; showAll: boolean; onToggleAll: () => void; })",
       "file": "src/components/LeadCard.tsx",
       "line": 130,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadSummary.tsx#scrollToLead",
       "name": "scrollToLead",
       "kind": "function",
       "sig": "function scrollToLead(id: string)",
       "file": "src/components/LeadSummary.tsx",
       "line": 6,
       "concept": "ui.leads",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/LeadSummary.tsx#LeadSummary",
       "name": "LeadSummary",
       "kind": "component",
       "sig": "function LeadSummary({ leads, statuses, now, selectedId, onSelect }: { leads: Lead[]; statuses: SourceStatus[]; now: number; selectedId: string | null; onSelect: (id: string) => void; })",
       "file": "src/components/LeadSummary.tsx",
       "line": 15,
       "concept": "ui.leads",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#CliRow",
       "local:orchestra:src/components/BackgroundTasks.tsx#Label"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#LeadTasks",
       "local:orchestra:src/components/BackgroundTasks.tsx#CliRow"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#LeadTasks",
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskRow"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#RunList",
       "local:orchestra:src/components/BackgroundTasks.tsx#RunRow"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskHistoryLists",
       "local:orchestra:src/components/BackgroundTasks.tsx#MoreRuns"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskHistoryLists",
       "local:orchestra:src/components/BackgroundTasks.tsx#RunList"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskRow",
       "local:orchestra:src/components/BackgroundTasks.tsx#CliRow"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskRow",
       "local:orchestra:src/components/BackgroundTasks.tsx#Label"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#UnattributedTaskDetails",
       "local:orchestra:src/components/BackgroundTasks.tsx#MoreRuns"
      ],
      [
       "local:orchestra:src/components/BackgroundTasks.tsx#UnattributedTaskDetails",
       "local:orchestra:src/components/BackgroundTasks.tsx#UnattributedRunRow"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "local:orchestra:src/components/BackgroundTasks.tsx#LeadTasks"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "local:orchestra:src/components/BackgroundTasks.tsx#TaskHistoryLists"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "local:orchestra:src/components/LeadCard.tsx#GotoButton"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "local:orchestra:src/components/LeadCard.tsx#MissionView"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadCard",
       "local:orchestra:src/components/LeadCard.tsx#PrLink"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#LeadList",
       "local:orchestra:src/components/LeadCard.tsx#LeadCard"
      ],
      [
       "local:orchestra:src/components/LeadCard.tsx#MissionView",
       "local:orchestra:src/components/LeadCard.tsx#etaText"
      ],
      [
       "local:orchestra:src/components/LeadSummary.tsx#LeadSummary",
       "local:orchestra:src/components/LeadSummary.tsx#scrollToLead"
      ]
     ],
     "callsOut": [
      "ui.collapse",
      "ui.viewmodel"
     ]
    },
    {
     "id": "ui.board",
     "name": "Orchestrator board",
     "summary": "The orchestrator's own groups of delegated work.",
     "files": [
      "src/components/OrchestratorBoard.tsx"
     ],
     "tests": [],
     "symbols": [
      {
       "id": "local:orchestra:src/components/OrchestratorBoard.tsx#OrchestratorBoard",
       "name": "OrchestratorBoard",
       "kind": "component",
       "sig": "function OrchestratorBoard({ orchestrator, taskHistory, statuses, now }: { orchestrator: OrchestratorGroup | null; taskHistory: TaskHistory; statuses: SourceStatus[]; now: number })",
       "file": "src/components/OrchestratorBoard.tsx",
       "line": 9,
       "concept": "ui.board",
       "tests": []
      }
     ],
     "calls": [],
     "callsOut": [
      "ui.collapse",
      "ui.leads",
      "ui.viewmodel"
     ]
    },
    {
     "id": "ui.messages",
     "name": "Messages panel",
     "summary": "Operator message threads rendered through a safe markdown model.",
     "files": [
      "src/components/MessagesPanel.tsx",
      "src/messages.ts"
     ],
     "tests": [
      {
       "file": "src/messages.test.ts",
       "cases": 3
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/components/MessagesPanel.tsx#MessagesPanel",
       "name": "MessagesPanel",
       "kind": "component",
       "sig": "function MessagesPanel({ threads, status, now }: { threads: MessageThread[]; status: SourceStatus; now: number })",
       "file": "src/components/MessagesPanel.tsx",
       "line": 7,
       "concept": "ui.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/MessagesPanel.tsx#ThreadDetail",
       "name": "ThreadDetail",
       "kind": "component",
       "sig": "function ThreadDetail({ thread, archived, now, reply, setReply, busy, error, onReply, onArchive, onGoto }: { thread: MessageThread; archived: boolean; now: number; reply: string; setReply(value: string): void; busy: boolean; error: string | null; onReply(event: FormEvent): void; onArchive(): void; onGoto(): void; })",
       "file": "src/components/MessagesPanel.tsx",
       "line": 107,
       "concept": "ui.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/MessagesPanel.tsx#MessageBody",
       "name": "MessageBody",
       "kind": "component",
       "sig": "function MessageBody({ threadId, entry, links, now }: { threadId: string; entry: MessageEntry; links: MessageLink[]; now: number })",
       "file": "src/components/MessagesPanel.tsx",
       "line": 135,
       "concept": "ui.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/MessagesPanel.tsx#Inline",
       "name": "Inline",
       "kind": "component",
       "sig": "function Inline({ part, threadId }: { part: InlinePart; threadId: string })",
       "file": "src/components/MessagesPanel.tsx",
       "line": 152,
       "concept": "ui.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/MessagesPanel.tsx#LinkButton",
       "name": "LinkButton",
       "kind": "component",
       "sig": "function LinkButton({ threadId, link }: { threadId: string; link: MessageLink })",
       "file": "src/components/MessagesPanel.tsx",
       "line": 159,
       "concept": "ui.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:src/messages.ts#visibleMessageThreads",
       "name": "visibleMessageThreads",
       "kind": "function",
       "sig": "function visibleMessageThreads<T extends Omit<MessageThread, \"links\">>( threads: T[], query: string, needsOnly: boolean, locallyArchived: ReadonlySet<string> = new Set(), ): T[]",
       "file": "src/messages.ts",
       "line": 6,
       "concept": "ui.messages",
       "tests": [
        "message search hides archived by default and reveals matching archived summaries"
       ]
      },
      {
       "id": "local:orchestra:src/messages.ts#shouldRefreshThread",
       "name": "shouldRefreshThread",
       "kind": "function",
       "sig": "function shouldRefreshThread(summary: MessageThread, detail: MessageThread | null): boolean",
       "file": "src/messages.ts",
       "line": 23,
       "concept": "ui.messages",
       "tests": [
        "open detail refreshes only when its summary activity advances"
       ]
      },
      {
       "id": "local:orchestra:src/messages.ts#markdownModel",
       "name": "markdownModel",
       "kind": "function",
       "sig": "function markdownModel(body: string, links: MessageLink[]): MarkdownBlock[]",
       "file": "src/messages.ts",
       "line": 37,
       "concept": "ui.messages",
       "tests": [
        "markdown model preserves text and enables only allowlisted links"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:src/components/MessagesPanel.tsx#MessageBody",
       "local:orchestra:src/components/MessagesPanel.tsx#Inline"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#MessageBody",
       "local:orchestra:src/messages.ts#markdownModel"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#MessagesPanel",
       "local:orchestra:src/components/MessagesPanel.tsx#ThreadDetail"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#MessagesPanel",
       "local:orchestra:src/messages.ts#shouldRefreshThread"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#MessagesPanel",
       "local:orchestra:src/messages.ts#visibleMessageThreads"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#ThreadDetail",
       "local:orchestra:src/components/MessagesPanel.tsx#LinkButton"
      ],
      [
       "local:orchestra:src/components/MessagesPanel.tsx#ThreadDetail",
       "local:orchestra:src/components/MessagesPanel.tsx#MessageBody"
      ]
     ],
     "callsOut": [
      "ui.viewmodel"
     ]
    },
    {
     "id": "ui.quota",
     "name": "Quota bar",
     "summary": "Remaining AI subscription quota and reset times.",
     "files": [
      "src/components/QuotaBar.tsx"
     ],
     "tests": [
      {
       "file": "src/components/QuotaBar.test.ts",
       "cases": 1
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/components/QuotaBar.tsx#cue",
       "name": "cue",
       "kind": "function",
       "sig": "const cue = (value: ReturnType<typeof pace>) =>",
       "file": "src/components/QuotaBar.tsx",
       "line": 6,
       "concept": "ui.quota",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/QuotaBar.tsx#reasonTitle",
       "name": "reasonTitle",
       "kind": "function",
       "sig": "const reasonTitle = (burn: boolean, reasons: string[]) =>",
       "file": "src/components/QuotaBar.tsx",
       "line": 7,
       "concept": "ui.quota",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/QuotaBar.tsx#QuotaCell",
       "name": "QuotaCell",
       "kind": "component",
       "sig": "function QuotaCell({ window, now, label, weekly }: { window: QuotaWindow | null; now: number; label: string; weekly: boolean })",
       "file": "src/components/QuotaBar.tsx",
       "line": 9,
       "concept": "ui.quota",
       "tests": []
      },
      {
       "id": "local:orchestra:src/components/QuotaBar.tsx#QuotaBar",
       "name": "QuotaBar",
       "kind": "component",
       "sig": "function QuotaBar({ entries, status, now }: { entries: QuotaRow[]; status: SourceStatus; now: number })",
       "file": "src/components/QuotaBar.tsx",
       "line": 18,
       "concept": "ui.quota",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:src/components/QuotaBar.tsx#QuotaBar",
       "local:orchestra:src/components/QuotaBar.tsx#QuotaCell"
      ],
      [
       "local:orchestra:src/components/QuotaBar.tsx#QuotaBar",
       "local:orchestra:src/components/QuotaBar.tsx#reasonTitle"
      ],
      [
       "local:orchestra:src/components/QuotaBar.tsx#QuotaCell",
       "local:orchestra:src/components/QuotaBar.tsx#cue"
      ],
      [
       "local:orchestra:src/components/QuotaBar.tsx#QuotaCell",
       "local:orchestra:src/components/QuotaBar.tsx#reasonTitle"
      ]
     ],
     "callsOut": [
      "ui.viewmodel"
     ]
    },
    {
     "id": "ui.viewmodel",
     "name": "View model",
     "summary": "Turns a snapshot into display rows, ages, percents and stale badges.",
     "files": [
      "src/viewModel.ts",
      "src/format.ts",
      "src/components/StaleBadge.tsx"
     ],
     "tests": [
      {
       "file": "src/viewModel.test.ts",
       "cases": 18
      },
      {
       "file": "src/format.test.ts",
       "cases": 4
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/components/StaleBadge.tsx#StaleBadge",
       "name": "StaleBadge",
       "kind": "component",
       "sig": "function StaleBadge({ statuses, now }: { statuses: SourceStatus[]; now: number })",
       "file": "src/components/StaleBadge.tsx",
       "line": 5,
       "concept": "ui.viewmodel",
       "tests": []
      },
      {
       "id": "local:orchestra:src/format.ts#formatAge",
       "name": "formatAge",
       "kind": "function",
       "sig": "function formatAge(ts: number, now: number): string",
       "file": "src/format.ts",
       "line": 2,
       "concept": "ui.viewmodel",
       "tests": [
        "formatAge picks the largest whole unit",
        "formatAge clamps future timestamps to 0s"
       ]
      },
      {
       "id": "local:orchestra:src/format.ts#formatUpdated",
       "name": "formatUpdated",
       "kind": "function",
       "sig": "function formatUpdated(ts: number | null, now: number): string",
       "file": "src/format.ts",
       "line": 10,
       "concept": "ui.viewmodel",
       "tests": []
      },
      {
       "id": "local:orchestra:src/format.ts#formatNext",
       "name": "formatNext",
       "kind": "function",
       "sig": "function formatNext(status: { nextRunAt?: number | null; paused?: boolean }, now: number): string | null",
       "file": "src/format.ts",
       "line": 15,
       "concept": "ui.viewmodel",
       "tests": [
        "formatNext rounds minutes up, says paused, and is null for fixed-interval sources"
       ]
      },
      {
       "id": "local:orchestra:src/format.ts#formatCount",
       "name": "formatCount",
       "kind": "function",
       "sig": "function formatCount(count: number, singular: string, plural = `${singular}s`): string",
       "file": "src/format.ts",
       "line": 21,
       "concept": "ui.viewmodel",
       "tests": []
      },
      {
       "id": "local:orchestra:src/format.ts#formatCountdown",
       "name": "formatCountdown",
       "kind": "function",
       "sig": "function formatCountdown(ts: number, now: number): string",
       "file": "src/format.ts",
       "line": 26,
       "concept": "ui.viewmodel",
       "tests": [
        "countdown uses two largest units and handles the minute boundary"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#pace",
       "name": "pace",
       "kind": "function",
       "sig": "function pace(window: QuotaWindow | null, now: number): Pace",
       "file": "src/viewModel.ts",
       "line": 7,
       "concept": "ui.viewmodel",
       "tests": [
        "chip levels and pace boundaries"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#elapsedPercent",
       "name": "elapsedPercent",
       "kind": "function",
       "sig": "function elapsedPercent(window: QuotaWindow, now: number): number | null",
       "file": "src/viewModel.ts",
       "line": 15,
       "concept": "ui.viewmodel",
       "tests": [
        "elapsed percent is clamped and needs a reset"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#pillLevel",
       "name": "pillLevel",
       "kind": "function",
       "sig": "function pillLevel(percentUsed: number): PillLevel",
       "file": "src/viewModel.ts",
       "line": 20,
       "concept": "ui.viewmodel",
       "tests": [
        "calculates quota pill levels at the documented thresholds"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#isStale",
       "name": "isStale",
       "kind": "function",
       "sig": "function isStale(status: SourceStatus, now: number): boolean",
       "file": "src/viewModel.ts",
       "line": 26,
       "concept": "ui.viewmodel",
       "tests": [
        "flags missing and over-age source data as stale"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#latestSourceAt",
       "name": "latestSourceAt",
       "kind": "function",
       "sig": "function latestSourceAt(statuses: SourceStatus[]): number | null",
       "file": "src/viewModel.ts",
       "line": 30,
       "concept": "ui.viewmodel",
       "tests": [
        "uses the oldest panel source update and exposes a short error class"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#staleError",
       "name": "staleError",
       "kind": "function",
       "sig": "function staleError(statuses: SourceStatus[]): SourceError | null",
       "file": "src/viewModel.ts",
       "line": 35,
       "concept": "ui.viewmodel",
       "tests": [
        "uses the oldest panel source update and exposes a short error class"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#panelIsStale",
       "name": "panelIsStale",
       "kind": "function",
       "sig": "function panelIsStale(statuses: SourceStatus[], now: number): boolean",
       "file": "src/viewModel.ts",
       "line": 39,
       "concept": "ui.viewmodel",
       "tests": [
        "flags missing and over-age source data as stale"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#isNeedStale",
       "name": "isNeedStale",
       "kind": "function",
       "sig": "function isNeedStale(item: NeedsJvItem, now: number): boolean",
       "file": "src/viewModel.ts",
       "line": 44,
       "concept": "ui.viewmodel",
       "tests": [
        "Needs JV requests turn stale after six hours"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#orderedLeads",
       "name": "orderedLeads",
       "kind": "function",
       "sig": "function orderedLeads(leads: Lead[]): Lead[]",
       "file": "src/viewModel.ts",
       "line": 48,
       "concept": "ui.viewmodel",
       "tests": [
        "keeps live and unknown leads ahead of dead leads"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#effectiveQuotaWindow",
       "name": "effectiveQuotaWindow",
       "kind": "function",
       "sig": "function effectiveQuotaWindow(row: QuotaRow, key: QuotaWindowKey, now: number): { window: QuotaWindow | null; capped: boolean }",
       "file": "src/viewModel.ts",
       "line": 61,
       "concept": "ui.viewmodel",
       "tests": [
        "an active observed cap overrides only its window and expires on renderer time"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#quotaRowExhausted",
       "name": "quotaRowExhausted",
       "kind": "function",
       "sig": "function quotaRowExhausted(row: QuotaRow, now: number): boolean",
       "file": "src/viewModel.ts",
       "line": 73,
       "concept": "ui.viewmodel",
       "tests": [
        "an active observed cap overrides only its window and expires on renderer time"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#quotaRows",
       "name": "quotaRows",
       "kind": "function",
       "sig": "function quotaRows(rows: QuotaRow[], now: number): QuotaTableRow[]",
       "file": "src/viewModel.ts",
       "line": 78,
       "concept": "ui.viewmodel",
       "tests": [
        "quota rows sort ahead, on pace, behind, 5h exhausted, then weekly exhausted"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#chipLevel",
       "name": "chipLevel",
       "kind": "function",
       "sig": "function chipLevel(chip: QuotaChip): PillLevel",
       "file": "src/viewModel.ts",
       "line": 93,
       "concept": "ui.viewmodel",
       "tests": [
        "chip levels and pace boundaries"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#cardBlockers",
       "name": "cardBlockers",
       "kind": "function",
       "sig": "function cardBlockers(blockers: Blocker[]): Blocker[]",
       "file": "src/viewModel.ts",
       "line": 98,
       "concept": "ui.viewmodel",
       "tests": [
        "lead cards keep only JV, error and limit blockers"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#allCliCalls",
       "name": "allCliCalls",
       "kind": "function",
       "sig": "const allCliCalls = (lead: Lead): CliCall[] =>",
       "file": "src/viewModel.ts",
       "line": 116,
       "concept": "ui.viewmodel",
       "tests": []
      },
      {
       "id": "local:orchestra:src/viewModel.ts#rollupActivity",
       "name": "rollupActivity",
       "kind": "function",
       "sig": "function rollupActivity(lead: Lead): RollupActivity",
       "file": "src/viewModel.ts",
       "line": 121,
       "concept": "ui.viewmodel",
       "tests": []
      },
      {
       "id": "local:orchestra:src/viewModel.ts#rollupState",
       "name": "rollupState",
       "kind": "function",
       "sig": "function rollupState(lead: Lead): RolledUpLeadState",
       "file": "src/viewModel.ts",
       "line": 156,
       "concept": "ui.viewmodel",
       "tests": [
        "app-owned summary rows and their live CLI calls never join a lead group",
        "books regression: five active Codex runs in its worktrees make an idle lead working",
        "rolled-up lead state recognises every working and waiting group member",
        "rolled-up lead state gives work, waits, then the main-derived JV count precedence before idle"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#rollupStateTitle",
       "name": "rollupStateTitle",
       "kind": "function",
       "sig": "function rollupStateTitle(lead: Lead): string",
       "file": "src/viewModel.ts",
       "line": 161,
       "concept": "ui.viewmodel",
       "tests": [
        "rolled-up lead state gives work, waits, then the main-derived JV count precedence before idle"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#leadSummaryRows",
       "name": "leadSummaryRows",
       "kind": "function",
       "sig": "function leadSummaryRows(leads: Lead[]): LeadSummaryRow[]",
       "file": "src/viewModel.ts",
       "line": 208,
       "concept": "ui.viewmodel",
       "tests": [
        "lead summary rows: lane counts, needs-JV count, dead last",
        "lead summary uses neutral placeholders until overview data arrives"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#workCounts",
       "name": "workCounts",
       "kind": "function",
       "sig": "function workCounts(tasks: BackgroundTask[], cliCalls: CliCall[], subagents: number): string",
       "file": "src/viewModel.ts",
       "line": 248,
       "concept": "ui.viewmodel",
       "tests": [
        "work counts read like the Claude Code footer; nested CLI calls count once"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#laneNote",
       "name": "laneNote",
       "kind": "function",
       "sig": "function laneNote(lane: Lane): string | null",
       "file": "src/viewModel.ts",
       "line": 256,
       "concept": "ui.viewmodel",
       "tests": [
        "lane note: pane state when processes make it working, count only otherwise"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#lanePr",
       "name": "lanePr",
       "kind": "function",
       "sig": "function lanePr(branch: string | null, prs: PullRequest[]): PullRequest | null",
       "file": "src/viewModel.ts",
       "line": 263,
       "concept": "ui.viewmodel",
       "tests": [
        "a lane shows the PR whose head branch equals its branch"
       ]
      },
      {
       "id": "local:orchestra:src/viewModel.ts#prBadges",
       "name": "prBadges",
       "kind": "function",
       "sig": "function prBadges(pr: PullRequest): { kind: string; text: string }[]",
       "file": "src/viewModel.ts",
       "line": 271,
       "concept": "ui.viewmodel",
       "tests": [
        "PR badges are text cues for draft, checks and review"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:src/components/StaleBadge.tsx#StaleBadge",
       "local:orchestra:src/format.ts#formatUpdated"
      ],
      [
       "local:orchestra:src/components/StaleBadge.tsx#StaleBadge",
       "local:orchestra:src/viewModel.ts#latestSourceAt"
      ],
      [
       "local:orchestra:src/components/StaleBadge.tsx#StaleBadge",
       "local:orchestra:src/viewModel.ts#panelIsStale"
      ],
      [
       "local:orchestra:src/components/StaleBadge.tsx#StaleBadge",
       "local:orchestra:src/viewModel.ts#staleError"
      ],
      [
       "local:orchestra:src/format.ts#formatUpdated",
       "local:orchestra:src/format.ts#formatAge"
      ],
      [
       "local:orchestra:src/viewModel.ts#laneNote",
       "local:orchestra:src/format.ts#formatCount"
      ],
      [
       "local:orchestra:src/viewModel.ts#leadSummaryRows",
       "local:orchestra:src/viewModel.ts#orderedLeads"
      ],
      [
       "local:orchestra:src/viewModel.ts#leadSummaryRows",
       "local:orchestra:src/viewModel.ts#rollupState"
      ],
      [
       "local:orchestra:src/viewModel.ts#leadSummaryRows",
       "local:orchestra:src/viewModel.ts#rollupStateTitle"
      ],
      [
       "local:orchestra:src/viewModel.ts#panelIsStale",
       "local:orchestra:src/viewModel.ts#isStale"
      ],
      [
       "local:orchestra:src/viewModel.ts#quotaRowExhausted",
       "local:orchestra:src/viewModel.ts#effectiveQuotaWindow"
      ],
      [
       "local:orchestra:src/viewModel.ts#quotaRows",
       "local:orchestra:src/viewModel.ts#effectiveQuotaWindow"
      ],
      [
       "local:orchestra:src/viewModel.ts#quotaRows",
       "local:orchestra:src/viewModel.ts#pace"
      ],
      [
       "local:orchestra:src/viewModel.ts#quotaRows",
       "local:orchestra:src/viewModel.ts#quotaRowExhausted"
      ],
      [
       "local:orchestra:src/viewModel.ts#rollupActivity",
       "local:orchestra:src/viewModel.ts#allCliCalls"
      ],
      [
       "local:orchestra:src/viewModel.ts#rollupState",
       "local:orchestra:src/viewModel.ts#rollupActivity"
      ],
      [
       "local:orchestra:src/viewModel.ts#rollupStateTitle",
       "local:orchestra:src/viewModel.ts#rollupActivity"
      ],
      [
       "local:orchestra:src/viewModel.ts#workCounts",
       "local:orchestra:src/format.ts#formatCount"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "ui.collapse",
     "name": "Collapsible sections",
     "summary": "Sections that remember whether they are open between sessions.",
     "files": [
      "src/collapse.ts",
      "src/useCollapsed.ts",
      "src/components/CollapsibleSection.tsx"
     ],
     "tests": [
      {
       "file": "src/collapse.test.ts",
       "cases": 3
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/collapse.ts#collapseKey",
       "name": "collapseKey",
       "kind": "function",
       "sig": "function collapseKey(panel: string, section: string): string",
       "file": "src/collapse.ts",
       "line": 1,
       "concept": "ui.collapse",
       "tests": [
        "collapse keys use the stable panel identity and section"
       ]
      },
      {
       "id": "local:orchestra:src/collapse.ts#leadCollapsePanel",
       "name": "leadCollapsePanel",
       "kind": "function",
       "sig": "function leadCollapsePanel(tmuxTarget: string | null): string",
       "file": "src/collapse.ts",
       "line": 5,
       "concept": "ui.collapse",
       "tests": [
        "collapse keys use the stable panel identity and section"
       ]
      },
      {
       "id": "local:orchestra:src/collapse.ts#defaultCollapsed",
       "name": "defaultCollapsed",
       "kind": "function",
       "sig": "function defaultCollapsed(storedValue: string | null, fallback: boolean): boolean",
       "file": "src/collapse.ts",
       "line": 9,
       "concept": "ui.collapse",
       "tests": [
        "sections use their configured default when no value is stored",
        "a stored collapse value wins over the configured default"
       ]
      },
      {
       "id": "local:orchestra:src/components/CollapsibleSection.tsx#CollapsibleSection",
       "name": "CollapsibleSection",
       "kind": "component",
       "sig": "function CollapsibleSection({ title, count, storageKey, defaultCollapsed = true, summary, children, className = \"board-section\" }: { title: string; count: number; storageKey: string; defaultCollapsed?: boolean; summary?: string; children: ReactNode; className?: string; })",
       "file": "src/components/CollapsibleSection.tsx",
       "line": 4,
       "concept": "ui.collapse",
       "tests": []
      },
      {
       "id": "local:orchestra:src/useCollapsed.ts#readCollapsed",
       "name": "readCollapsed",
       "kind": "function",
       "sig": "function readCollapsed(key: string, defaultValue: boolean): boolean",
       "file": "src/useCollapsed.ts",
       "line": 4,
       "concept": "ui.collapse",
       "tests": []
      },
      {
       "id": "local:orchestra:src/useCollapsed.ts#useCollapsed",
       "name": "useCollapsed",
       "kind": "function",
       "sig": "function useCollapsed(key: string, defaultCollapsed: boolean): [boolean, () => void]",
       "file": "src/useCollapsed.ts",
       "line": 12,
       "concept": "ui.collapse",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:src/components/CollapsibleSection.tsx#CollapsibleSection",
       "local:orchestra:src/useCollapsed.ts#useCollapsed"
      ],
      [
       "local:orchestra:src/useCollapsed.ts#readCollapsed",
       "local:orchestra:src/collapse.ts#defaultCollapsed"
      ],
      [
       "local:orchestra:src/useCollapsed.ts#useCollapsed",
       "local:orchestra:src/useCollapsed.ts#readCollapsed"
      ]
     ],
     "callsOut": []
    }
   ]
  },
  {
   "id": "core",
   "name": "Core poller",
   "summary": "Runs each source on its own timer and merges the results into one allowlisted snapshot.",
   "children": [
    {
     "id": "core.sources",
     "name": "Sources",
     "summary": "Commands to run and parsers for agents, lanes, quota, processes, tasks and PRs.",
     "files": [
      "orchestra-core/sources.ts"
     ],
     "tests": [
      {
       "file": "electron/sources.test.ts",
       "cases": 49
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseObject",
       "name": "parseObject",
       "kind": "function",
       "sig": "function parseObject(stdout: string): Obj",
       "file": "orchestra-core/sources.ts",
       "line": 81,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#attributionPath",
       "name": "attributionPath",
       "kind": "function",
       "sig": "function attributionPath(v: unknown): string | null",
       "file": "orchestra-core/sources.ts",
       "line": 88,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseSubagentStatus",
       "name": "parseSubagentStatus",
       "kind": "function",
       "sig": "function parseSubagentStatus(stdout: string, now = Date.now()): StatusGroup[]",
       "file": "orchestra-core/sources.ts",
       "line": 96,
       "concept": "core.sources",
       "tests": [
        "subagent-status: keeps allowlisted fields, converts times, truncates prompt",
        "free text is scrubbed before truncation",
        "missing fields are tolerated",
        "wrong top-level shape throws (poller records 'parse')"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#missionEta",
       "name": "missionEta",
       "kind": "function",
       "sig": "function missionEta(v: unknown): { eta: number | null; state: MissionEtaState }",
       "file": "orchestra-core/sources.ts",
       "line": 161,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseMission",
       "name": "parseMission",
       "kind": "function",
       "sig": "function parseMission(v: unknown): Mission | null",
       "file": "orchestra-core/sources.ts",
       "line": 176,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseMissions",
       "name": "parseMissions",
       "kind": "function",
       "sig": "function parseMissions(v: unknown): Pick<RegistryLead, \"missionMetadata\" | \"mission\" | \"laneMissions\">",
       "file": "orchestra-core/sources.ts",
       "line": 199,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseLeadRegistry",
       "name": "parseLeadRegistry",
       "kind": "function",
       "sig": "function parseLeadRegistry(stdout: string): RegistryLead[]",
       "file": "orchestra-core/sources.ts",
       "line": 214,
       "concept": "core.sources",
       "tests": [
        "missions: lead metadata and exact lane keys join; unmatched and invalid schema stay explicit",
        "mission title path canaries cannot cross desktop or mobile snapshot boundaries",
        "lead registry: fields kept, last 3 notes oldest first",
        "lead registry missions: legacy absence, malformed states, strict ETA, and deterministic lane bound",
        "lead registry missions reject paths embedded in allowlisted titles",
        "free text is scrubbed before truncation",
        "missing fields are tolerated",
        "wrong top-level shape throws (poller records 'parse')",
        "processes: agent pids are live registry pids plus subagent-status owner pids"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#blockerSince",
       "name": "blockerSince",
       "kind": "function",
       "sig": "function blockerSince(v: unknown, generatedAt: number): number | null",
       "file": "orchestra-core/sources.ts",
       "line": 256,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseLeadOverview",
       "name": "parseLeadOverview",
       "kind": "function",
       "sig": "function parseLeadOverview(stdout: string, now = Date.now()): OverviewEntry[]",
       "file": "orchestra-core/sources.ts",
       "line": 272,
       "concept": "core.sources",
       "tests": [
        "lead overview: skips unregistered and keeps allowlisted blocker metadata",
        "lead overview: allowlists canonical goals and rejects malformed goal rows",
        "lead overview: blocker descriptions are scrubbed, first-line capped, and timestamps accept seconds, milliseconds, or ISO",
        "waiting detail is allowlisted exactly and unknown safe states stay visible",
        "free text is scrubbed before truncation",
        "missing fields are tolerated",
        "processes source runs lsof cwd and tmux list-panes only when lanes have paths, and parses lane busy counts"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#expiryMs",
       "name": "expiryMs",
       "kind": "function",
       "sig": "function expiryMs(v: unknown): number | null",
       "file": "orchestra-core/sources.ts",
       "line": 353,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#countdown",
       "name": "countdown",
       "kind": "function",
       "sig": "function countdown(ms: number, now: number): string",
       "file": "orchestra-core/sources.ts",
       "line": 360,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#soonest",
       "name": "soonest",
       "kind": "function",
       "sig": "function soonest(values: unknown[], now: number): { title: string; urgent: boolean; at: number } | null",
       "file": "orchestra-core/sources.ts",
       "line": 369,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#when",
       "name": "when",
       "kind": "function",
       "sig": "const when = (e: { title: string; urgent: boolean; at: number } | null, now: number) =>",
       "file": "orchestra-core/sources.ts",
       "line": 377,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#resetsChip",
       "name": "resetsChip",
       "kind": "function",
       "sig": "const resetsChip = (count: number, expiries: unknown[], now: number): QuotaChip[] =>",
       "file": "orchestra-core/sources.ts",
       "line": 379,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#codexResets",
       "name": "codexResets",
       "kind": "function",
       "sig": "function codexResets(v: unknown, now: number): QuotaChip[]",
       "file": "orchestra-core/sources.ts",
       "line": 386,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#claudeCredits",
       "name": "claudeCredits",
       "kind": "function",
       "sig": "function claudeCredits(v: unknown, now: number): QuotaChip[]",
       "file": "orchestra-core/sources.ts",
       "line": 394,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#reasons",
       "name": "reasons",
       "kind": "function",
       "sig": "const reasons = (v: unknown) =>",
       "file": "orchestra-core/sources.ts",
       "line": 410,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#quotaWindow",
       "name": "quotaWindow",
       "kind": "function",
       "sig": "const quotaWindow = (v: unknown): QuotaWindow | null =>",
       "file": "orchestra-core/sources.ts",
       "line": 411,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#observedQuotaCap",
       "name": "observedQuotaCap",
       "kind": "function",
       "sig": "const observedQuotaCap = (v: unknown): QuotaRow[\"observedCap\"] =>",
       "file": "orchestra-core/sources.ts",
       "line": 416,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "name": "parseQuota",
       "kind": "function",
       "sig": "function parseQuota(stdout: string, now = Date.now()): QuotaData",
       "file": "orchestra-core/sources.ts",
       "line": 423,
       "concept": "core.sources",
       "tests": [
        "quota snapshot parses windows, credits, burn and grok without free text",
        "quota snapshot allowlists stale and observed-cap metadata without its message",
        "quota expiry chips show countdowns and retain full dates in hover titles",
        "quota snapshot tolerates missing fields and garbage",
        "missing fields are tolerated"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#etimeS",
       "name": "etimeS",
       "kind": "function",
       "sig": "function etimeS(s: string): number | null",
       "file": "orchestra-core/sources.ts",
       "line": 505,
       "concept": "core.sources",
       "tests": [
        "etime: MM:SS, HH:MM:SS, D-HH:MM:SS"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parsePs",
       "name": "parsePs",
       "kind": "function",
       "sig": "function parsePs(stdout: string): PsRow[]",
       "file": "orchestra-core/sources.ts",
       "line": 510,
       "concept": "core.sources",
       "tests": [
        "agent children: direct, older than 10 s, no MCP servers or codex app-server, looks through a wrapped agent binary",
        "cpu sums the whole subtree",
        "live CLI detection keeps explicit headless roots and drops interactive and plumbing processes",
        "lanes: counts detached processes by cwd or argv, minus the lane's own pane tree and interactive processes",
        "lanes: cwd scan candidates exclude pane trees and system processes but keep detached user work"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parsePsCommands",
       "name": "parsePsCommands",
       "kind": "function",
       "sig": "function parsePsCommands(stdout: string): Map<number, string>",
       "file": "orchestra-core/sources.ts",
       "line": 521,
       "concept": "core.sources",
       "tests": [
        "selected ps command lines are truncated to 4 KB before task parsing"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#withCommands",
       "name": "withCommands",
       "kind": "function",
       "sig": "function withCommands(rows: PsRow[], commands: Map<number, string>): PsRow[]",
       "file": "orchestra-core/sources.ts",
       "line": 530,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#shellWord",
       "name": "shellWord",
       "kind": "function",
       "sig": "function shellWord(s: string, i: number): string | null",
       "file": "orchestra-core/sources.ts",
       "line": 535,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#taskCommand",
       "name": "taskCommand",
       "kind": "function",
       "sig": "function taskCommand(raw: string): string",
       "file": "orchestra-core/sources.ts",
       "line": 556,
       "concept": "core.sources",
       "tests": [
        "task command: eval'd part, '\\\\'' and '\\\"'\\\"' escapes, grok wrapper, boilerplate fallback"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#taskKind",
       "name": "taskKind",
       "kind": "function",
       "sig": "function taskKind(raw: string, stdout: Stdout | undefined): TaskKind",
       "file": "orchestra-core/sources.ts",
       "line": 578,
       "concept": "core.sources",
       "tests": [
        "kind: task shell stdout to a tasks/*.output file is a shell, to a pipe or unix socket a monitor, else other"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#agentChildren",
       "name": "agentChildren",
       "kind": "function",
       "sig": "function agentChildren(rows: PsRow[], agents: Iterable<number>): (PsRow & { agentPid: number })[]",
       "file": "orchestra-core/sources.ts",
       "line": 588,
       "concept": "core.sources",
       "tests": [
        "agent children: direct, older than 10 s, no MCP servers or codex app-server, looks through a wrapped agent binary"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#orchestratorProcess",
       "name": "orchestratorProcess",
       "kind": "function",
       "sig": "function orchestratorProcess(rows: PsRow[], stdout: string, now = Date.now()): OrchestratorProcess | null",
       "file": "orchestra-core/sources.ts",
       "line": 605,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#childMap",
       "name": "childMap",
       "kind": "function",
       "sig": "function childMap(rows: PsRow[]): Map<number, PsRow[]>",
       "file": "orchestra-core/sources.ts",
       "line": 624,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#subtree",
       "name": "subtree",
       "kind": "function",
       "sig": "function subtree(kids: Map<number, PsRow[]>, pid: number): Set<number>",
       "file": "orchestra-core/sources.ts",
       "line": 631,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#subtreeCpu",
       "name": "subtreeCpu",
       "kind": "function",
       "sig": "function subtreeCpu(rows: PsRow[], pid: number): number",
       "file": "orchestra-core/sources.ts",
       "line": 644,
       "concept": "core.sources",
       "tests": [
        "cpu sums the whole subtree"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseLsofOutputs",
       "name": "parseLsofOutputs",
       "kind": "function",
       "sig": "function parseLsofOutputs(stdout: string): Map<number, Stdout>",
       "file": "orchestra-core/sources.ts",
       "line": 658,
       "concept": "core.sources",
       "tests": [
        "lsof -F: keeps only Claude task output files",
        "kind: task shell stdout to a tasks/*.output file is a shell, to a pipe or unix socket a monitor, else other"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseLsofNames",
       "name": "parseLsofNames",
       "kind": "function",
       "sig": "function parseLsofNames(stdout: string): Map<number, string>",
       "file": "orchestra-core/sources.ts",
       "line": 674,
       "concept": "core.sources",
       "tests": [
        "lanes: lsof cwd and tmux pane parsing"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parsePanes",
       "name": "parsePanes",
       "kind": "function",
       "sig": "function parsePanes(stdout: string): Map<string, number>",
       "file": "orchestra-core/sources.ts",
       "line": 685,
       "concept": "core.sources",
       "tests": [
        "lanes: lsof cwd and tmux pane parsing"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#isInteractive",
       "name": "isInteractive",
       "kind": "function",
       "sig": "const isInteractive = (raw: string) =>",
       "file": "orchestra-core/sources.ts",
       "line": 702,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#liveCliCandidatePids",
       "name": "liveCliCandidatePids",
       "kind": "function",
       "sig": "function liveCliCandidatePids(rows: PsRow[]): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 705,
       "concept": "core.sources",
       "tests": [
        "live CLI detection keeps explicit headless roots and drops interactive and plumbing processes"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#liveCliTool",
       "name": "liveCliTool",
       "kind": "function",
       "sig": "function liveCliTool(raw: string): LiveCliProcess[\"tool\"] | null",
       "file": "orchestra-core/sources.ts",
       "line": 711,
       "concept": "core.sources",
       "tests": [
        "live CLI detection keeps explicit headless roots and drops interactive and plumbing processes"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#escapeRe",
       "name": "escapeRe",
       "kind": "function",
       "sig": "const escapeRe = (s: string) =>",
       "file": "orchestra-core/sources.ts",
       "line": 724,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#isUnder",
       "name": "isUnder",
       "kind": "function",
       "sig": "const isUnder = (cwd: string, dir: string) =>",
       "file": "orchestra-core/sources.ts",
       "line": 727,
       "concept": "core.sources",
       "tests": [
        "lanes: path matching is exact or nested, never a string prefix"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids",
       "name": "cwdCandidatePids",
       "kind": "function",
       "sig": "function cwdCandidatePids(rows: PsRow[], panes: Map<string, number>): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 735,
       "concept": "core.sources",
       "tests": [
        "lanes: cwd scan candidates exclude pane trees and system processes but keep detached user work"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#cwdRootPids",
       "name": "cwdRootPids",
       "kind": "function",
       "sig": "function cwdRootPids(rows: PsRow[], panes: Map<string, number>): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 747,
       "concept": "core.sources",
       "tests": [
        "lanes: cwd scan candidates exclude pane trees and system processes but keep detached user work"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#cwdScanPids",
       "name": "cwdScanPids",
       "kind": "function",
       "sig": "function cwdScanPids(rows: PsRow[], panes: Map<string, number>): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 756,
       "concept": "core.sources",
       "tests": [
        "lanes: cwd scan candidates exclude pane trees and system processes but keep detached user work"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds",
       "name": "inheritedCandidateCwds",
       "kind": "function",
       "sig": "function inheritedCandidateCwds(rows: PsRow[], panes: Map<string, number>, measuredCwds: Map<number, string>, lanePaths: string[] = []): Map<number, string>",
       "file": "orchestra-core/sources.ts",
       "line": 771,
       "concept": "core.sources",
       "tests": [
        "lanes: cwd scan candidates exclude pane trees and system processes but keep detached user work"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "name": "laneBusy",
       "kind": "function",
       "sig": "function laneBusy(rows: PsRow[], cwds: Map<number, string>, panes: Map<string, number>, lanes: (LaneRef & { key: string })[]): Record<string, number>",
       "file": "orchestra-core/sources.ts",
       "line": 793,
       "concept": "core.sources",
       "tests": [
        "lanes: counts detached processes by cwd or argv, minus the lane's own pane tree and interactive processes"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#commandCandidatePids",
       "name": "commandCandidatePids",
       "kind": "function",
       "sig": "function commandCandidatePids(rows: PsRow[], taskPids: Iterable<number>, cwds: Map<number, string>, panes: Map<string, number>, lanes: (LaneRef & { key: string })[]): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 815,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#agentPids",
       "name": "agentPids",
       "kind": "function",
       "sig": "function agentPids(states: Pick<SourceStates, \"leadRegistry\" | \"subagentStatus\">): number[]",
       "file": "orchestra-core/sources.ts",
       "line": 832,
       "concept": "core.sources",
       "tests": [
        "processes: agent pids are live registry pids plus subagent-status owner pids"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#laneRefs",
       "name": "laneRefs",
       "kind": "function",
       "sig": "function laneRefs(states: Pick<SourceStates, \"leadOverview\">): (LaneRef & { key: string })[]",
       "file": "orchestra-core/sources.ts",
       "line": 839,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "name": "runProcesses",
       "kind": "function",
       "sig": "async function runProcesses(exec: (argv: string[], maxStdoutBytes?: number) => Promise<string>, states: SourceStates, now: () => number): Promise<string>",
       "file": "orchestra-core/sources.ts",
       "line": 856,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "name": "parseProcesses",
       "kind": "function",
       "sig": "function parseProcesses(stdout: string, now: number, appPid: number): ProcessesData",
       "file": "orchestra-core/sources.ts",
       "line": 889,
       "concept": "core.sources",
       "tests": [
        "process source parser receives the injected application pid"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#revealablePath",
       "name": "revealablePath",
       "kind": "function",
       "sig": "function revealablePath(p: unknown, home: string): string | null",
       "file": "orchestra-core/sources.ts",
       "line": 956,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#foldTasks",
       "name": "foldTasks",
       "kind": "function",
       "sig": "function foldTasks(rows: unknown[], now: number, alive: Set<number>, home: string): TaskRunRow[]",
       "file": "orchestra-core/sources.ts",
       "line": 963,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parseTasks",
       "name": "parseTasks",
       "kind": "function",
       "sig": "function parseTasks(stdout: string, home: string, now: number): TaskRunRow[]",
       "file": "orchestra-core/sources.ts",
       "line": 991,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#githubSlug",
       "name": "githubSlug",
       "kind": "function",
       "sig": "function githubSlug(remote: string): string | null",
       "file": "orchestra-core/sources.ts",
       "line": 1007,
       "concept": "core.sources",
       "tests": [
        "githubSlug accepts GitHub https/ssh remotes only"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#rollupChecks",
       "name": "rollupChecks",
       "kind": "function",
       "sig": "function rollupChecks(v: unknown): PrChecks",
       "file": "orchestra-core/sources.ts",
       "line": 1016,
       "concept": "core.sources",
       "tests": [
        "rollupChecks folds check runs and status contexts into pass|fail|pending|none"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parsePrList",
       "name": "parsePrList",
       "kind": "function",
       "sig": "function parsePrList(stdout: string): PullRequest[]",
       "file": "orchestra-core/sources.ts",
       "line": 1026,
       "concept": "core.sources",
       "tests": [
        "parsePrList allowlists fields, scrubs titles and drops non-GitHub urls"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#parsePrs",
       "name": "parsePrs",
       "kind": "function",
       "sig": "function parsePrs(stdout: string, prev?: unknown): PrsData",
       "file": "orchestra-core/sources.ts",
       "line": 1053,
       "concept": "core.sources",
       "tests": [
        "parsePrs keeps a repo's last good PRs when its fetch failed and drops repos no lead uses"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#runPrs",
       "name": "runPrs",
       "kind": "function",
       "sig": "async function runPrs(exec: (argv: string[], maxStdoutBytes?: number) => Promise<string>, states: SourceStates): Promise<string>",
       "file": "orchestra-core/sources.ts",
       "line": 1071,
       "concept": "core.sources",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#sourcePaths",
       "name": "sourcePaths",
       "kind": "function",
       "sig": "function sourcePaths(home: string)",
       "file": "orchestra-core/sources.ts",
       "line": 1096,
       "concept": "core.sources",
       "tests": [
        "core source catalogue preserves every schedule and fixed command prefix",
        "file-backed sources use only injected bounded reads and message actions keep fixed argv"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sources.ts#createSources",
       "name": "createSources",
       "kind": "function",
       "sig": "function createSources(runtime: SourceRuntime): Source[]",
       "file": "orchestra-core/sources.ts",
       "line": 1105,
       "concept": "core.sources",
       "tests": [
        "direct core and Electron adapters are byte-equivalent to pre-extraction fixture outputs",
        "direct core import performs the source and final Snapshot leak scans",
        "summary lookup behavior is identical through direct core and Electron imports",
        "core source catalogue preserves every schedule and fixed command prefix",
        "file-backed sources use only injected bounded reads and message actions keep fixed argv",
        "process source parser receives the injected application pid"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/sources.ts#agentChildren",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#claudeCredits",
       "local:orchestra:orchestra-core/sources.ts#resetsChip"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#claudeCredits",
       "local:orchestra:orchestra-core/sources.ts#soonest"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#claudeCredits",
       "local:orchestra:orchestra-core/sources.ts#when"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#codexResets",
       "local:orchestra:orchestra-core/sources.ts#resetsChip"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#commandCandidatePids",
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#commandCandidatePids",
       "local:orchestra:orchestra-core/sources.ts#isUnder"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#foldTasks"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#parseLeadOverview"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#parseProcesses"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#parseQuota"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#parseSubagentStatus"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#parseTasks"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#runProcesses"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#createSources",
       "local:orchestra:orchestra-core/sources.ts#sourcePaths"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids",
       "local:orchestra:orchestra-core/sources.ts#subtree"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#cwdRootPids",
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#cwdScanPids",
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#foldTasks",
       "local:orchestra:orchestra-core/sources.ts#attributionPath"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#foldTasks",
       "local:orchestra:orchestra-core/sources.ts#revealablePath"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds",
       "local:orchestra:orchestra-core/sources.ts#cwdCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds",
       "local:orchestra:orchestra-core/sources.ts#cwdRootPids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds",
       "local:orchestra:orchestra-core/sources.ts#isUnder"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "local:orchestra:orchestra-core/sources.ts#escapeRe"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "local:orchestra:orchestra-core/sources.ts#isInteractive"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "local:orchestra:orchestra-core/sources.ts#isUnder"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#laneBusy",
       "local:orchestra:orchestra-core/sources.ts#subtree"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#orchestratorProcess",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseLeadOverview",
       "local:orchestra:orchestra-core/sources.ts#blockerSince"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseLeadOverview",
       "local:orchestra:orchestra-core/sources.ts#parseObject"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseLeadRegistry",
       "local:orchestra:orchestra-core/sources.ts#attributionPath"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseLeadRegistry",
       "local:orchestra:orchestra-core/sources.ts#parseMissions"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseMission",
       "local:orchestra:orchestra-core/sources.ts#missionEta"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseMissions",
       "local:orchestra:orchestra-core/sources.ts#parseMission"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parsePrList",
       "local:orchestra:orchestra-core/sources.ts#rollupChecks"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#agentChildren"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#attributionPath"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#laneBusy"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#liveCliCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#liveCliTool"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#parseLsofNames"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#parseLsofOutputs"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#parsePanes"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#parsePs"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#parsePsCommands"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#subtree"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#subtreeCpu"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#taskCommand"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#taskKind"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseProcesses",
       "local:orchestra:orchestra-core/sources.ts#withCommands"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parsePrs",
       "local:orchestra:orchestra-core/sources.ts#attributionPath"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parsePrs",
       "local:orchestra:orchestra-core/sources.ts#githubSlug"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parsePrs",
       "local:orchestra:orchestra-core/sources.ts#parsePrList"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parsePs",
       "local:orchestra:orchestra-core/sources.ts#etimeS"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#claudeCredits"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#codexResets"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#observedQuotaCap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#parseObject"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#quotaWindow"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseQuota",
       "local:orchestra:orchestra-core/sources.ts#reasons"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseSubagentStatus",
       "local:orchestra:orchestra-core/sources.ts#parseObject"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#parseTasks",
       "local:orchestra:orchestra-core/sources.ts#foldTasks"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#quotaWindow",
       "local:orchestra:orchestra-core/sources.ts#reasons"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#resetsChip",
       "local:orchestra:orchestra-core/sources.ts#soonest"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#resetsChip",
       "local:orchestra:orchestra-core/sources.ts#when"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#revealablePath",
       "local:orchestra:orchestra-core/sources.ts#isUnder"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#agentChildren"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#agentPids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#commandCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#cwdScanPids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#inheritedCandidateCwds"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#laneRefs"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#liveCliCandidatePids"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#orchestratorProcess"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#parseLsofNames"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#parsePanes"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runProcesses",
       "local:orchestra:orchestra-core/sources.ts#parsePs"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#runPrs",
       "local:orchestra:orchestra-core/sources.ts#githubSlug"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#subtreeCpu",
       "local:orchestra:orchestra-core/sources.ts#childMap"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#subtreeCpu",
       "local:orchestra:orchestra-core/sources.ts#subtree"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#taskCommand",
       "local:orchestra:orchestra-core/sources.ts#shellWord"
      ],
      [
       "local:orchestra:orchestra-core/sources.ts#when",
       "local:orchestra:orchestra-core/sources.ts#countdown"
      ]
     ],
     "callsOut": [
      "core.messages",
      "core.safety"
     ]
    },
    {
     "id": "core.poller",
     "name": "Poll scheduler",
     "summary": "Staggered timers that never overlap a source and keep its last good result.",
     "files": [
      "orchestra-core/poller.ts"
     ],
     "tests": [
      {
       "file": "electron/poller.test.ts",
       "cases": 8
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/poller.ts#noop",
       "name": "noop",
       "kind": "function",
       "sig": "const noop = () =>",
       "file": "orchestra-core/poller.ts",
       "line": 36,
       "concept": "core.poller",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/poller.ts#classify",
       "name": "classify",
       "kind": "function",
       "sig": "function classify(err: unknown): SourceError",
       "file": "orchestra-core/poller.ts",
       "line": 39,
       "concept": "core.poller",
       "tests": [
        "realExec: stdout, missing binary, and abort kills the child"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/poller.ts#initialStates",
       "name": "initialStates",
       "kind": "function",
       "sig": "function initialStates(sources: Source[]): SourceStates",
       "file": "orchestra-core/poller.ts",
       "line": 46,
       "concept": "core.poller",
       "tests": [
        "file-backed sources use only injected bounded reads and message actions keep fixed argv",
        "snapshot.test.ts",
        "empty states give an empty snapshot with every source not ok",
        "messages source loads default and archived summaries with fixed argv under one source state",
        "processes: agent pids are live registry pids plus subagent-status owner pids",
        "processes source uses a cheap tree scan then selected full argv with an injected exec",
        "processes source falls back to the orchestrator pane when subagent-status is quiet",
        "processes source leaves the orchestrator fallback empty when its pane is absent",
        "processes source runs lsof cwd and tmux list-panes only when lanes have paths, and parses lane busy counts",
        "prs source runs only git remote get-url and gh pr list, once per distinct root and repo"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/poller.ts#startPoller",
       "name": "startPoller",
       "kind": "function",
       "sig": "function startPoller( sources: Source[], opts: { exec: ExecFn; onChange: (name: SourceName) => void; log?: (line: string) => void; shouldRun?: () => boolean; runtime?: PollerRuntime }, )",
       "file": "orchestra-core/poller.ts",
       "line": 52,
       "concept": "core.poller",
       "tests": [
        "core poller uses injected clock and timer hooks"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/poller.ts#startPoller",
       "local:orchestra:orchestra-core/poller.ts#classify"
      ],
      [
       "local:orchestra:orchestra-core/poller.ts#startPoller",
       "local:orchestra:orchestra-core/poller.ts#initialStates"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "core.snapshot",
     "name": "Snapshot builder",
     "summary": "Merges source states into a snapshot, derives needs-JV and runs the final leak scan.",
     "files": [
      "orchestra-core/snapshot.ts"
     ],
     "tests": [
      {
       "file": "electron/snapshot.test.ts",
       "cases": 31
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#isAppOwnedWhy",
       "name": "isAppOwnedWhy",
       "kind": "function",
       "sig": "const isAppOwnedWhy = (why: string | null): boolean =>",
       "file": "orchestra-core/snapshot.ts",
       "line": 16,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#isOrchestrator",
       "name": "isOrchestrator",
       "kind": "function",
       "sig": "const isOrchestrator = (tmux: string) =>",
       "file": "orchestra-core/snapshot.ts",
       "line": 19,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#noSummaries",
       "name": "noSummaries",
       "kind": "function",
       "sig": "const noSummaries: SummaryLookup = () =>",
       "file": "orchestra-core/snapshot.ts",
       "line": 24,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#busyLane",
       "name": "busyLane",
       "kind": "function",
       "sig": "function busyLane(lane: Lane, busy: number): Lane",
       "file": "orchestra-core/snapshot.ts",
       "line": 28,
       "concept": "core.snapshot",
       "tests": [
        "lane busy in detached processes: quiet pane states become working, JV states are kept; counts reach the snapshot"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#isAtOrUnder",
       "name": "isAtOrUnder",
       "kind": "function",
       "sig": "function isAtOrUnder(candidate: string, root: string): boolean",
       "file": "orchestra-core/snapshot.ts",
       "line": 33,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#tmuxSession",
       "name": "tmuxSession",
       "kind": "function",
       "sig": "function tmuxSession(target: string | null): string | null",
       "file": "orchestra-core/snapshot.ts",
       "line": 37,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#historyGroup",
       "name": "historyGroup",
       "kind": "function",
       "sig": "function historyGroup<T extends TaskRun>(runs: T[]): TaskHistoryGroup & { runs: T[] }",
       "file": "orchestra-core/snapshot.ts",
       "line": 43,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#deriveNeedsJv",
       "name": "deriveNeedsJv",
       "kind": "function",
       "sig": "function deriveNeedsJv(leads: Lead[], threads: MessageThread[]): NeedsJvItem[]",
       "file": "orchestra-core/snapshot.ts",
       "line": 54,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "name": "buildSnapshot",
       "kind": "function",
       "sig": "function buildSnapshot(states: SourceStates, now: number, summaryOf: SummaryLookup = noSummaries): Snapshot",
       "file": "orchestra-core/snapshot.ts",
       "line": 76,
       "concept": "core.snapshot",
       "tests": [
        "direct core and Electron adapters are byte-equivalent to pre-extraction fixture outputs",
        "direct core import performs the source and final Snapshot leak scans",
        "summary lookup behavior is identical through direct core and Electron imports",
        "empty states give an empty snapshot with every source not ok",
        "orchestrator is the jv:0.1 group",
        "orchestrator falls back to its tmux pane process when subagent-status has no group",
        "leads: registry joined with overview on registered.id, dead leads last",
        "missions: lead metadata and exact lane keys join; unmatched and invalid schema stay explicit",
        "background tasks join to the orchestrator by owner_pid and to live leads by registry pid",
        "task:reveal lookup: only a pid in the snapshot with a TASK_OUTPUT file",
        "needs-JV derives only from awaiting decide/blocked message threads",
        "notify rows and overview blockers no longer create competing needs-JV items",
        "full pipeline: no canary or token survives JSON.stringify(snapshot)",
        "leak scan blanks the leaking source and marks it 'leak'",
        "final JSON leak scan blanks the section even when a source object hides its value",
        "CLI calls running inside a background shell are nested under it, the rest stay separate, none twice",
        "leads get the CLI calls of the subagent-status group they own",
        "app-owned summary rows and their live CLI calls never join a lead group",
        "lane busy in detached processes: quiet pane states become working, JV states are kept; counts reach the snapshot",
        "task history: finished rows are grouped, newest first, and only attribution bugs are unattributed",
        "task history attribution uses tmux sessions before cwd, then longest bounded worktree roots",
        "lead CLI runs use owner tmux first, bounded longest roots, dedup, and the documented status windows",
        "books regression: five active Codex runs in its worktrees make an idle lead working",
        "lead CLI hover details are capped while aggregate counts remain exact",
        "unattributed task bugs expose only scrubbed capped diagnostics and never join a normal group",
        "task history caps every owner group at 50 rows while retaining total done and failed counts",
        "a live CLI call takes the why of the running task with its pid",
        "taskRun:reveal lookup: only a finished run in the snapshot with a revealable output path",
        "a lead gets its repo root's PRs; the root and dropped fields never reach the snapshot",
        "pr:open lookup: only a GitHub PR url shown in the snapshot",
        "mobile v1 snapshot carries no path-valued field from the full fixture snapshot",
        "mobile background commands reduce a leading executable path to its basename",
        "mission title path canaries cannot cross desktop or mobile snapshot boundaries"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#taskOutputPath",
       "name": "taskOutputPath",
       "kind": "function",
       "sig": "function taskOutputPath(snapshot: Snapshot, processes: unknown, pid: unknown): string | null",
       "file": "orchestra-core/snapshot.ts",
       "line": 291,
       "concept": "core.snapshot",
       "tests": [
        "task:reveal lookup: only a pid in the snapshot with a TASK_OUTPUT file"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#taskRunOutputPathWithHome",
       "name": "taskRunOutputPathWithHome",
       "kind": "function",
       "sig": "function taskRunOutputPathWithHome(snapshot: Snapshot, tasks: unknown, id: unknown, home: string): string | null",
       "file": "orchestra-core/snapshot.ts",
       "line": 305,
       "concept": "core.snapshot",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/snapshot.ts#prOpenUrl",
       "name": "prOpenUrl",
       "kind": "function",
       "sig": "function prOpenUrl(snapshot: Snapshot, url: unknown): string | null",
       "file": "orchestra-core/snapshot.ts",
       "line": 314,
       "concept": "core.snapshot",
       "tests": [
        "pr:open lookup: only a GitHub PR url shown in the snapshot"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#busyLane"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#deriveNeedsJv"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#historyGroup"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#isAppOwnedWhy"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#isAtOrUnder"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#isOrchestrator"
      ],
      [
       "local:orchestra:orchestra-core/snapshot.ts#buildSnapshot",
       "local:orchestra:orchestra-core/snapshot.ts#tmuxSession"
      ]
     ],
     "callsOut": [
      "core.safety",
      "core.sources"
     ]
    },
    {
     "id": "core.messages",
     "name": "Messages model",
     "summary": "Allowlists message JSON and validates actions against the current snapshot.",
     "files": [
      "orchestra-core/messages.ts",
      "orchestra-core/message-actions.ts"
     ],
     "tests": [],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/message-actions.ts#showMessageWithBin",
       "name": "showMessageWithBin",
       "kind": "function",
       "sig": "const showMessageWithBin = (messageBin: string, snapshot: Snapshot, id: unknown, exec: MessageExec) =>",
       "file": "orchestra-core/message-actions.ts",
       "line": 6,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/message-actions.ts#replyMessageWithBin",
       "name": "replyMessageWithBin",
       "kind": "function",
       "sig": "async function replyMessageWithBin(messageBin: string, snapshot: Snapshot, id: unknown, body: unknown, exec: MessageExec): Promise<MessageActionResult>",
       "file": "orchestra-core/message-actions.ts",
       "line": 8,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/message-actions.ts#archiveMessageWithBin",
       "name": "archiveMessageWithBin",
       "kind": "function",
       "sig": "async function archiveMessageWithBin(messageBin: string, snapshot: Snapshot, id: unknown, exec: MessageExec): Promise<MessageActionResult>",
       "file": "orchestra-core/message-actions.ts",
       "line": 20,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/message-actions.ts#createMessageActions",
       "name": "createMessageActions",
       "kind": "function",
       "sig": "function createMessageActions(messageBin: string)",
       "file": "orchestra-core/message-actions.ts",
       "line": 32,
       "concept": "core.messages",
       "tests": [
        "file-backed sources use only injected bounded reads and message actions keep fixed argv"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/message-actions.ts#messageLink",
       "name": "messageLink",
       "kind": "function",
       "sig": "function messageLink(snapshot: Snapshot, id: unknown, target: unknown): MessageLink | null",
       "file": "orchestra-core/message-actions.ts",
       "line": 41,
       "concept": "core.messages",
       "tests": [
        "links and go-to targets must belong to a current thread"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#markdown",
       "name": "markdown",
       "kind": "function",
       "sig": "function markdown(v: unknown): string",
       "file": "orchestra-core/messages.ts",
       "line": 28,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#safeMessageLink",
       "name": "safeMessageLink",
       "kind": "function",
       "sig": "function safeMessageLink(v: unknown): MessageLink | null",
       "file": "orchestra-core/messages.ts",
       "line": 33,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#parseEntry",
       "name": "parseEntry",
       "kind": "function",
       "sig": "function parseEntry(v: unknown, fallbackId: string): MessageEntry",
       "file": "orchestra-core/messages.ts",
       "line": 51,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#parseThread",
       "name": "parseThread",
       "kind": "function",
       "sig": "function parseThread(v: unknown): { thread: MessageThread; target: MessageTarget } | null",
       "file": "orchestra-core/messages.ts",
       "line": 61,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#parseMessages",
       "name": "parseMessages",
       "kind": "function",
       "sig": "function parseMessages(stdout: string, limit = THREAD_LIMIT): MessagesData",
       "file": "orchestra-core/messages.ts",
       "line": 101,
       "concept": "core.messages",
       "tests": [
        "file-backed sources use only injected bounded reads and message actions keep fixed argv",
        "message source strictly allowlists, scrubs, bounds, and sorts the CLI contract",
        "default and archived contracts combine with independent bounds and deduplication",
        "message contract enforces documented thread, entry, link, and body bounds",
        "messages.test.ts",
        "links and go-to targets must belong to a current thread",
        "peek detail uses fixed read-only argv, current ids only, and parses the schema-v1 peek contract",
        "notify rows and overview blockers no longer create competing needs-JV items",
        "app-owned summary rows and their live CLI calls never join a lead group"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#combineMessageLists",
       "name": "combineMessageLists",
       "kind": "function",
       "sig": "function combineMessageLists(activeStdout: string, archivedStdout: string): string",
       "file": "orchestra-core/messages.ts",
       "line": 124,
       "concept": "core.messages",
       "tests": [
        "core-equivalence.test.ts",
        "default and archived contracts combine with independent bounds and deduplication",
        "snapshot.test.ts"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#parseShownMessage",
       "name": "parseShownMessage",
       "kind": "function",
       "sig": "function parseShownMessage(stdout: string, expectedId: string): MessageThread | null",
       "file": "orchestra-core/messages.ts",
       "line": 137,
       "concept": "core.messages",
       "tests": [
        "bounded direct-core and Electron message detail remain byte-equivalent",
        "show contract allowlists message events, appends read state, and scrubs bodies",
        "message contract enforces documented thread, entry, link, and body bounds",
        "peek detail uses fixed read-only argv, current ids only, and parses the schema-v1 peek contract",
        "mobile v1 message detail matches the hand-written golden fixture",
        "remote egress keeps path link label and kind but never the absolute target",
        "toMobileThread copies only the declared fields"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#currentThread",
       "name": "currentThread",
       "kind": "function",
       "sig": "const currentThread = (snapshot: Snapshot, id: unknown): MessageThread | null =>",
       "file": "orchestra-core/messages.ts",
       "line": 155,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#showArgv",
       "name": "showArgv",
       "kind": "function",
       "sig": "const showArgv = (id: string, peek: boolean): string[] =>",
       "file": "orchestra-core/messages.ts",
       "line": 159,
       "concept": "core.messages",
       "tests": [
        "peek detail uses fixed read-only argv, current ids only, and parses the schema-v1 peek contract"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#messageDetail",
       "name": "messageDetail",
       "kind": "function",
       "sig": "async function messageDetail(messageBin: string, snapshot: Snapshot, id: unknown, exec: MessageExec, peek: boolean): Promise<MessageActionResult>",
       "file": "orchestra-core/messages.ts",
       "line": 161,
       "concept": "core.messages",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/messages.ts#createMessagePeek",
       "name": "createMessagePeek",
       "kind": "function",
       "sig": "const createMessagePeek = (messageBin: string) =>",
       "file": "orchestra-core/messages.ts",
       "line": 173,
       "concept": "core.messages",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/message-actions.ts#archiveMessageWithBin",
       "local:orchestra:orchestra-core/messages.ts#currentThread"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#createMessageActions",
       "local:orchestra:orchestra-core/message-actions.ts#archiveMessageWithBin"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#createMessageActions",
       "local:orchestra:orchestra-core/message-actions.ts#replyMessageWithBin"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#createMessageActions",
       "local:orchestra:orchestra-core/message-actions.ts#showMessageWithBin"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#createMessageActions",
       "local:orchestra:orchestra-core/messages.ts#messageDetail"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#messageLink",
       "local:orchestra:orchestra-core/messages.ts#currentThread"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#replyMessageWithBin",
       "local:orchestra:orchestra-core/messages.ts#currentThread"
      ],
      [
       "local:orchestra:orchestra-core/message-actions.ts#showMessageWithBin",
       "local:orchestra:orchestra-core/messages.ts#messageDetail"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#createMessagePeek",
       "local:orchestra:orchestra-core/messages.ts#messageDetail"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#messageDetail",
       "local:orchestra:orchestra-core/messages.ts#currentThread"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#messageDetail",
       "local:orchestra:orchestra-core/messages.ts#parseShownMessage"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#messageDetail",
       "local:orchestra:orchestra-core/messages.ts#showArgv"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#parseEntry",
       "local:orchestra:orchestra-core/messages.ts#markdown"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#parseMessages",
       "local:orchestra:orchestra-core/messages.ts#parseThread"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#parseShownMessage",
       "local:orchestra:orchestra-core/messages.ts#parseEntry"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#parseShownMessage",
       "local:orchestra:orchestra-core/messages.ts#parseThread"
      ],
      [
       "local:orchestra:orchestra-core/messages.ts#parseThread",
       "local:orchestra:orchestra-core/messages.ts#parseEntry"
      ]
     ],
     "callsOut": [
      "core.safety"
     ]
    },
    {
     "id": "core.safety",
     "name": "Safety filters",
     "summary": "Field allowlists, truncation, banned-key scans and tmux target checks.",
     "files": [
      "orchestra-core/sanitize.ts",
      "orchestra-core/tmux.ts"
     ],
     "tests": [
      {
       "file": "electron/sanitize.test.ts",
       "cases": 3
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#obj",
       "name": "obj",
       "kind": "function",
       "sig": "const obj = (v: unknown): Obj =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 6,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#arr",
       "name": "arr",
       "kind": "function",
       "sig": "const arr = (v: unknown): unknown[] =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 7,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#looksRandom",
       "name": "looksRandom",
       "kind": "function",
       "sig": "function looksRandom(run: string): boolean",
       "file": "orchestra-core/sanitize.ts",
       "line": 32,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#scrubSecrets",
       "name": "scrubSecrets",
       "kind": "function",
       "sig": "function scrubSecrets(s: string): string",
       "file": "orchestra-core/sanitize.ts",
       "line": 39,
       "concept": "core.safety",
       "tests": [
        "scrubs every supported secret shape",
        "ordinary paths are not redacted; long random tokens inside them still are"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#str",
       "name": "str",
       "kind": "function",
       "sig": "function str(v: unknown, max = 200): string | null",
       "file": "orchestra-core/sanitize.ts",
       "line": 44,
       "concept": "core.safety",
       "tests": [
        "scrubs before truncation when a token crosses the limit"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#firstLine",
       "name": "firstLine",
       "kind": "function",
       "sig": "function firstLine(v: unknown, max = 200): string | null",
       "file": "orchestra-core/sanitize.ts",
       "line": 51,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#num",
       "name": "num",
       "kind": "function",
       "sig": "const num = (v: unknown): number | null =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 57,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#bool",
       "name": "bool",
       "kind": "function",
       "sig": "const bool = (v: unknown): boolean =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 58,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#isoMs",
       "name": "isoMs",
       "kind": "function",
       "sig": "function isoMs(v: unknown): number | null",
       "file": "orchestra-core/sanitize.ts",
       "line": 61,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#secMs",
       "name": "secMs",
       "kind": "function",
       "sig": "const secMs = (v: unknown): number | null =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 67,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#agentState",
       "name": "agentState",
       "kind": "function",
       "sig": "const agentState = (v: unknown): AgentState =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 71,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#leadMode",
       "name": "leadMode",
       "kind": "function",
       "sig": "const leadMode = (v: unknown): LeadMode =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 72,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#liveness",
       "name": "liveness",
       "kind": "function",
       "sig": "const liveness = (v: unknown): Liveness =>",
       "file": "orchestra-core/sanitize.ts",
       "line": 73,
       "concept": "core.safety",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/sanitize.ts#findLeak",
       "name": "findLeak",
       "kind": "function",
       "sig": "function findLeak(v: unknown, at = \"$\"): string | null",
       "file": "orchestra-core/sanitize.ts",
       "line": 86,
       "concept": "core.safety",
       "tests": [
        "scrubs every supported secret shape",
        "ordinary paths are not redacted; long random tokens inside them still are",
        "processes: table is allowlisted, scrubbed, single-line and 120 chars; startedAt from etime",
        "tasks allowlist: only the contract fields, scrubbed and truncated; output kept as a revealable path and its basename",
        "parsePrList allowlists fields, scrubs titles and drops non-GitHub urls"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/sanitize.ts#findLeak",
       "local:orchestra:orchestra-core/sanitize.ts#scrubSecrets"
      ],
      [
       "local:orchestra:orchestra-core/sanitize.ts#firstLine",
       "local:orchestra:orchestra-core/sanitize.ts#scrubSecrets"
      ],
      [
       "local:orchestra:orchestra-core/sanitize.ts#scrubSecrets",
       "local:orchestra:orchestra-core/sanitize.ts#looksRandom"
      ],
      [
       "local:orchestra:orchestra-core/sanitize.ts#secMs",
       "local:orchestra:orchestra-core/sanitize.ts#num"
      ],
      [
       "local:orchestra:orchestra-core/sanitize.ts#str",
       "local:orchestra:orchestra-core/sanitize.ts#scrubSecrets"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "core.runtime",
     "name": "Node runtime",
     "summary": "Fixed-argv command runner, file reads, clock and process liveness for Node hosts.",
     "files": [
      "orchestra-core/node.ts",
      "orchestra-core/index.ts"
     ],
     "tests": [],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/node.ts#childEnv",
       "name": "childEnv",
       "kind": "function",
       "sig": "function childEnv(): NodeJS.ProcessEnv",
       "file": "orchestra-core/node.ts",
       "line": 11,
       "concept": "core.runtime",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/node.ts#realExec",
       "name": "realExec",
       "kind": "function",
       "sig": "const realExec: ExecFn = (argv, signal, maxStdoutBytes = MAX_STDOUT) =>",
       "file": "orchestra-core/node.ts",
       "line": 20,
       "concept": "core.runtime",
       "tests": [
        "realExec: stdout, missing binary, and abort kills the child"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/node.ts#readTail",
       "name": "readTail",
       "kind": "function",
       "sig": "async function readTail(file: string, maxBytes: number): Promise<string>",
       "file": "orchestra-core/node.ts",
       "line": 54,
       "concept": "core.runtime",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/node.ts#pidAlive",
       "name": "pidAlive",
       "kind": "function",
       "sig": "function pidAlive(pid: number): boolean",
       "file": "orchestra-core/node.ts",
       "line": 68,
       "concept": "core.runtime",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/node.ts#createNodeRuntime",
       "name": "createNodeRuntime",
       "kind": "function",
       "sig": "function createNodeRuntime(overrides: Partial<SourceRuntime> = {}): SourceRuntime",
       "file": "orchestra-core/node.ts",
       "line": 78,
       "concept": "core.runtime",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/node.ts#realExec",
       "local:orchestra:orchestra-core/node.ts#childEnv"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "core.contracts",
     "name": "Contracts",
     "summary": "Snapshot and mobile API v1 types, and the projection from one to the other.",
     "files": [
      "shared/snapshot.ts",
      "shared/mobile-api.ts",
      "orchestra-core/mobile.ts"
     ],
     "tests": [
      {
       "file": "electron/mobile.test.ts",
       "cases": 4
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#safeLabel",
       "name": "safeLabel",
       "kind": "function",
       "sig": "const safeLabel = (label: string): string =>",
       "file": "orchestra-core/mobile.ts",
       "line": 21,
       "concept": "core.contracts",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileBackgroundTask",
       "name": "toMobileBackgroundTask",
       "kind": "function",
       "sig": "const toMobileBackgroundTask = (task: BackgroundTask): BackgroundTask =>",
       "file": "orchestra-core/mobile.ts",
       "line": 24,
       "concept": "core.contracts",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#mobileMarkdown",
       "name": "mobileMarkdown",
       "kind": "function",
       "sig": "function mobileMarkdown(body: string): string",
       "file": "orchestra-core/mobile.ts",
       "line": 30,
       "concept": "core.contracts",
       "tests": [
        "mobile markdown drops non-https destinations and keeps https links"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileLink",
       "name": "toMobileLink",
       "kind": "function",
       "sig": "function toMobileLink(link: MessageLink): MobileMessageLink | null",
       "file": "orchestra-core/mobile.ts",
       "line": 42,
       "concept": "core.contracts",
       "tests": [
        "remote egress keeps path link label and kind but never the absolute target"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileEntry",
       "name": "toMobileEntry",
       "kind": "function",
       "sig": "const toMobileEntry = (entry: MessageEntry): MessageEntry =>",
       "file": "orchestra-core/mobile.ts",
       "line": 47,
       "concept": "core.contracts",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileThread",
       "name": "toMobileThread",
       "kind": "function",
       "sig": "function toMobileThread(thread: MessageThread): MobileMessageThread",
       "file": "orchestra-core/mobile.ts",
       "line": 54,
       "concept": "core.contracts",
       "tests": [
        "bounded direct-core and Electron message detail remain byte-equivalent",
        "mobile v1 message detail matches the hand-written golden fixture",
        "remote egress keeps path link label and kind but never the absolute target",
        "toMobileThread copies only the declared fields"
       ]
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileUnattributed",
       "name": "toMobileUnattributed",
       "kind": "function",
       "sig": "const toMobileUnattributed = (run: UnattributedTaskRun): MobileUnattributedTaskRun =>",
       "file": "orchestra-core/mobile.ts",
       "line": 72,
       "concept": "core.contracts",
       "tests": []
      },
      {
       "id": "local:orchestra:orchestra-core/mobile.ts#toMobileSnapshot",
       "name": "toMobileSnapshot",
       "kind": "function",
       "sig": "function toMobileSnapshot(snapshot: Snapshot): MobileSnapshot",
       "file": "orchestra-core/mobile.ts",
       "line": 88,
       "concept": "core.contracts",
       "tests": [
        "direct core and Electron adapters are byte-equivalent to pre-extraction fixture outputs",
        "mobile v1 snapshot carries no path-valued field from the full fixture snapshot",
        "mobile background commands reduce a leading executable path to its basename",
        "mission title path canaries cannot cross desktop or mobile snapshot boundaries"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:orchestra-core/mobile.ts#mobileMarkdown",
       "local:orchestra:orchestra-core/mobile.ts#safeLabel"
      ],
      [
       "local:orchestra:orchestra-core/mobile.ts#toMobileEntry",
       "local:orchestra:orchestra-core/mobile.ts#mobileMarkdown"
      ],
      [
       "local:orchestra:orchestra-core/mobile.ts#toMobileLink",
       "local:orchestra:orchestra-core/mobile.ts#safeLabel"
      ]
     ],
     "callsOut": []
    }
   ]
  },
  {
   "id": "service",
   "name": "Phone preview service",
   "summary": "A loopback HTTP service that serves the snapshot to paired phones over Tailscale.",
   "children": [
    {
     "id": "service.runtime",
     "name": "Service runtime",
     "summary": "Production entrypoint that composes its own poller, auth and server.",
     "files": [
      "service/entrypoint.ts",
      "service/daemon.ts"
     ],
     "tests": [
      {
       "file": "service/daemon.test.ts",
       "cases": 12
      },
      {
       "file": "service/custody-race.test.ts",
       "cases": 18
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/daemon.ts#fixedMessageExec",
       "name": "fixedMessageExec",
       "kind": "function",
       "sig": "const fixedMessageExec: MessageExec = (file, args, signal) =>",
       "file": "service/daemon.ts",
       "line": 43,
       "concept": "service.runtime",
       "tests": []
      },
      {
       "id": "local:orchestra:service/daemon.ts#startHeadlessService",
       "name": "startHeadlessService",
       "kind": "function",
       "sig": "async function startHeadlessService(options: DaemonOptions): Promise<RunningReadService>",
       "file": "service/daemon.ts",
       "line": 51,
       "concept": "service.runtime",
       "tests": [
        "source_failure_preserves_core_last_good_snapshot and recovery replaces it",
        "daemon production composition validates current ids and invokes only msg show --peek",
        "daemon forwards only an explicitly reviewed MagicDNS host"
       ]
      },
      {
       "id": "local:orchestra:service/entrypoint.ts#configuredPort",
       "name": "configuredPort",
       "kind": "function",
       "sig": "function configuredPort(): number",
       "file": "service/entrypoint.ts",
       "line": 18,
       "concept": "service.runtime",
       "tests": []
      },
      {
       "id": "local:orchestra:service/entrypoint.ts#startEntrypoint",
       "name": "startEntrypoint",
       "kind": "function",
       "sig": "async function startEntrypoint(hook?: CustodyHook): Promise<{ service: Awaited<ReturnType<typeof startHeadlessService>>; close(): Promise<void> }>",
       "file": "service/entrypoint.ts",
       "line": 27,
       "concept": "service.runtime",
       "tests": [
        "support identity swap at ${point} fails startup without foreign mutation or listener",
        "support identity swap during rollback preserves foreign targets and removes owned listeners",
        "support identity swap during shutdown preserves foreign targets and closes owned listeners",
        "a post-start support swap is never reported healthy and closes both listeners",
        "the content-free startup audit is a fatal precondition before either listener",
        "unhooked concurrent support flipper yields no foreign start, mode change, or socket",
        "shutdown after a support swap never unlinks the foreign admin.sock and preserves the closed socket name",
        "watchdog shutdown after a support swap never unlinks the foreign admin.sock",
        "entrypoint rollback after a support swap never unlinks the foreign admin.sock",
        "admin rollback after a support swap never unlinks the foreign admin.sock and preserves its closed socket name",
        "a transient swap around admin listen binds only inside the held directory",
        "a swap inside the intercepted admin listen call binds only inside the held directory",
        "unhooked flipper during shutdown never deletes the foreign admin.sock",
        "entrypoint close releases the retained custody descriptor, watchdog, and both listeners"
       ]
      },
      {
       "id": "local:orchestra:service/entrypoint.ts#main",
       "name": "main",
       "kind": "function",
       "sig": "async function main(): Promise<void>",
       "file": "service/entrypoint.ts",
       "line": 97,
       "concept": "service.runtime",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:service/entrypoint.ts#main",
       "local:orchestra:service/entrypoint.ts#startEntrypoint"
      ],
      [
       "local:orchestra:service/entrypoint.ts#startEntrypoint",
       "local:orchestra:service/daemon.ts#startHeadlessService"
      ],
      [
       "local:orchestra:service/entrypoint.ts#startEntrypoint",
       "local:orchestra:service/entrypoint.ts#configuredPort"
      ]
     ],
     "callsOut": [
      "core.messages",
      "core.poller",
      "core.runtime",
      "core.snapshot",
      "core.sources",
      "service.api",
      "service.audit",
      "service.auth",
      "service.pairing",
      "service.registry"
     ]
    },
    {
     "id": "service.api",
     "name": "Snapshot API and event stream",
     "summary": "Conditional snapshot reads, revision-only SSE, rate limits and a final egress scan.",
     "files": [
      "service/server.ts",
      "service/egress.ts",
      "service/rate-limit.ts"
     ],
     "tests": [
      {
       "file": "service/server.test.ts",
       "cases": 34
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/egress.ts#EgressPathError",
       "name": "EgressPathError",
       "kind": "class",
       "sig": "class EgressPathError extends Error",
       "file": "service/egress.ts",
       "line": 5,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/egress.ts#isForbiddenPathLeaf",
       "name": "isForbiddenPathLeaf",
       "kind": "function",
       "sig": "function isForbiddenPathLeaf(value: string): boolean",
       "file": "service/egress.ts",
       "line": 13,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/egress.ts#assertMobileEgress",
       "name": "assertMobileEgress",
       "kind": "function",
       "sig": "function assertMobileEgress(value: unknown): void",
       "file": "service/egress.ts",
       "line": 17,
       "concept": "service.api",
       "tests": [
        "runtime_egress_scan_rejects_path_and_secret_canaries while permitting path prose"
       ]
      },
      {
       "id": "local:orchestra:service/egress.ts#encodeMobileJson",
       "name": "encodeMobileJson",
       "kind": "function",
       "sig": "function encodeMobileJson(value: unknown): string",
       "file": "service/egress.ts",
       "line": 36,
       "concept": "service.api",
       "tests": [
        "runtime_egress_scan_rejects_path_and_secret_canaries while permitting path prose"
       ]
      },
      {
       "id": "local:orchestra:service/egress.ts#encodeSnapshotRevisionEvent",
       "name": "encodeSnapshotRevisionEvent",
       "kind": "function",
       "sig": "function encodeSnapshotRevisionEvent(value: SnapshotRevisionEvent): string",
       "file": "service/egress.ts",
       "line": 42,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/rate-limit.ts#BoundedRateLimits",
       "name": "BoundedRateLimits",
       "kind": "class",
       "sig": "class BoundedRateLimits",
       "file": "service/rate-limit.ts",
       "line": 1,
       "concept": "service.api",
       "tests": [
        "rate buckets are bounded and isolated by action and device"
       ]
      },
      {
       "id": "local:orchestra:service/server.ts#testAuthorizationFor",
       "name": "testAuthorizationFor",
       "kind": "function",
       "sig": "function testAuthorizationFor(environment: string | undefined, authorize: Authorize | undefined): Authorize | undefined",
       "file": "service/server.ts",
       "line": 94,
       "concept": "service.api",
       "tests": [
        "daemon authorization injection is test-only and production resolves fail-closed"
       ]
      },
      {
       "id": "local:orchestra:service/server.ts#mobileHeaders",
       "name": "mobileHeaders",
       "kind": "function",
       "sig": "function mobileHeaders(requestId: string, type: \"application/json\" | \"text/event-stream\"): Record<string, string>",
       "file": "service/server.ts",
       "line": 98,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#sendJson",
       "name": "sendJson",
       "kind": "function",
       "sig": "function sendJson(response: ServerResponse, requestId: string, status: number, body: unknown, extra: Record<string, string> = {}): void",
       "file": "service/server.ts",
       "line": 108,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#sendCredential",
       "name": "sendCredential",
       "kind": "function",
       "sig": "function sendCredential(response: ServerResponse, requestId: string, credential: IssuedCredential): void",
       "file": "service/server.ts",
       "line": 120,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#sendEmpty",
       "name": "sendEmpty",
       "kind": "function",
       "sig": "function sendEmpty(response: ServerResponse, status: number, headers: Record<string, string> = {}): void",
       "file": "service/server.ts",
       "line": 130,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#rawHeaderValues",
       "name": "rawHeaderValues",
       "kind": "function",
       "sig": "function rawHeaderValues(request: IncomingMessage, name: string): string[]",
       "file": "service/server.ts",
       "line": 135,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#isLoopbackPeer",
       "name": "isLoopbackPeer",
       "kind": "function",
       "sig": "function isLoopbackPeer(address: string | undefined): boolean",
       "file": "service/server.ts",
       "line": 143,
       "concept": "service.api",
       "tests": [
        "non_loopback_peer_rejected by the immediate-peer predicate"
       ]
      },
      {
       "id": "local:orchestra:service/server.ts#requestAuthorityAllowed",
       "name": "requestAuthorityAllowed",
       "kind": "function",
       "sig": "function requestAuthorityAllowed(request: IncomingMessage, allowedMagicDnsHost: string | undefined, requireOrigin = false): boolean",
       "file": "service/server.ts",
       "line": 147,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#ifNoneMatch",
       "name": "ifNoneMatch",
       "kind": "function",
       "sig": "function ifNoneMatch(raw: string | undefined, etag: string): boolean",
       "file": "service/server.ts",
       "line": 160,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#subjectFor",
       "name": "subjectFor",
       "kind": "function",
       "sig": "async function subjectFor(request: IncomingMessage, authorize: Authorize | undefined): Promise<import(\"./auth\").AuthorizedDevice | null>",
       "file": "service/server.ts",
       "line": 164,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#actionFor",
       "name": "actionFor",
       "kind": "function",
       "sig": "function actionFor(pathname: string): AuditAction",
       "file": "service/server.ts",
       "line": 178,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#outcomeFor",
       "name": "outcomeFor",
       "kind": "function",
       "sig": "function outcomeFor(status: number): AuditOutcome",
       "file": "service/server.ts",
       "line": 188,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#readPairBody",
       "name": "readPairBody",
       "kind": "function",
       "sig": "async function readPairBody(request: IncomingMessage): Promise<{ code: unknown; deviceLabel: unknown } | null>",
       "file": "service/server.ts",
       "line": 197,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#staticFilesFor",
       "name": "staticFilesFor",
       "kind": "function",
       "sig": "async function staticFilesFor(root: string): Promise<StaticFiles>",
       "file": "service/server.ts",
       "line": 238,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#serveStatic",
       "name": "serveStatic",
       "kind": "function",
       "sig": "async function serveStatic(files: StaticFiles, root: string, pathname: string, request: IncomingMessage, response: ServerResponse): Promise<boolean>",
       "file": "service/server.ts",
       "line": 255,
       "concept": "service.api",
       "tests": []
      },
      {
       "id": "local:orchestra:service/server.ts#startReadService",
       "name": "startReadService",
       "kind": "function",
       "sig": "async function startReadService(options: ReadServiceOptions): Promise<RunningReadService>",
       "file": "service/server.ts",
       "line": 284,
       "concept": "service.api",
       "tests": [
        "server.test.ts"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:service/egress.ts#assertMobileEgress",
       "local:orchestra:service/egress.ts#EgressPathError"
      ],
      [
       "local:orchestra:service/egress.ts#assertMobileEgress",
       "local:orchestra:service/egress.ts#isForbiddenPathLeaf"
      ],
      [
       "local:orchestra:service/egress.ts#encodeMobileJson",
       "local:orchestra:service/egress.ts#assertMobileEgress"
      ],
      [
       "local:orchestra:service/egress.ts#encodeSnapshotRevisionEvent",
       "local:orchestra:service/egress.ts#EgressPathError"
      ],
      [
       "local:orchestra:service/egress.ts#encodeSnapshotRevisionEvent",
       "local:orchestra:service/egress.ts#assertMobileEgress"
      ],
      [
       "local:orchestra:service/server.ts#readPairBody",
       "local:orchestra:service/server.ts#rawHeaderValues"
      ],
      [
       "local:orchestra:service/server.ts#requestAuthorityAllowed",
       "local:orchestra:service/server.ts#rawHeaderValues"
      ],
      [
       "local:orchestra:service/server.ts#sendCredential",
       "local:orchestra:service/server.ts#mobileHeaders"
      ],
      [
       "local:orchestra:service/server.ts#sendCredential",
       "local:orchestra:service/server.ts#sendJson"
      ],
      [
       "local:orchestra:service/server.ts#sendJson",
       "local:orchestra:service/egress.ts#encodeMobileJson"
      ],
      [
       "local:orchestra:service/server.ts#sendJson",
       "local:orchestra:service/server.ts#mobileHeaders"
      ],
      [
       "local:orchestra:service/server.ts#serveStatic",
       "local:orchestra:service/server.ts#sendEmpty"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/egress.ts#encodeMobileJson"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/egress.ts#encodeSnapshotRevisionEvent"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/rate-limit.ts#BoundedRateLimits"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#actionFor"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#ifNoneMatch"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#isLoopbackPeer"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#mobileHeaders"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#outcomeFor"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#rawHeaderValues"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#readPairBody"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#requestAuthorityAllowed"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#sendCredential"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#sendEmpty"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#sendJson"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#serveStatic"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#staticFilesFor"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#subjectFor"
      ],
      [
       "local:orchestra:service/server.ts#startReadService",
       "local:orchestra:service/server.ts#testAuthorizationFor"
      ]
     ],
     "callsOut": [
      "core.contracts",
      "core.safety",
      "service.audit",
      "service.auth"
     ]
    },
    {
     "id": "service.pairing",
     "name": "Device pairing",
     "summary": "Local-only admin socket for pairing, rotating and revoking phones.",
     "files": [
      "service/device-admin.ts",
      "service/admin-socket.ts"
     ],
     "tests": [
      {
       "file": "service/device-admin.test.ts",
       "cases": 17
      },
      {
       "file": "service/admin-socket.test.ts",
       "cases": 4
      },
      {
       "file": "service/custody-counterexample.test.ts",
       "cases": 6
      },
      {
       "file": "service/custody-replacement.test.ts",
       "cases": 10
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/admin-socket.ts#inDirectory",
       "name": "inDirectory",
       "kind": "function",
       "sig": "function inDirectory(directory: string, run: () => void): void",
       "file": "service/admin-socket.ts",
       "line": 15,
       "concept": "service.pairing",
       "tests": []
      },
      {
       "id": "local:orchestra:service/admin-socket.ts#assertInertDirectory",
       "name": "assertInertDirectory",
       "kind": "function",
       "sig": "async function assertInertDirectory(): Promise<void>",
       "file": "service/admin-socket.ts",
       "line": 22,
       "concept": "service.pairing",
       "tests": []
      },
      {
       "id": "local:orchestra:service/admin-socket.ts#startAdminSocket",
       "name": "startAdminSocket",
       "kind": "function",
       "sig": "async function startAdminSocket(socketPath: string, admin: DeviceAdministrator, custody?: DirectoryCustody): Promise<RunningAdminSocket>",
       "file": "service/admin-socket.ts",
       "line": 27,
       "concept": "service.pairing",
       "tests": [
        "local device administrator is a mode-0600 Unix capability with no remote-router dependency",
        "admin socket executes only one bounded terminal UTF-8 JSON-line frame",
        "admin socket rejects ${kind} parent before binding and preserves target bytes and modes",
        "admin socket accepts a safe ${kind} parent through shared custody",
        "socket-for-socket overwrite before observation is refused and never adopted or removed",
        "admin rollback after the bound admin.sock is replaced keeps the replacement and leaves no staging directory",
        "admin rollback after the bound admin.sock is replaced before its identity is read keeps the replacement",
        "admin success path creates admin.sock exclusively at 0600 and never links, chmods or stages by name",
        "an existing entry at admin.sock refuses the bind atomically and is untouched",
        "shutdown after admin.sock is replaced keeps the replacement; libuv's close-time unlink is inert",
        "shutdown never invokes named unlink even after the final socket observation",
        "unhooked admin.sock racer: no named deletion or staging directory"
       ]
      },
      {
       "id": "local:orchestra:service/device-admin.ts#verifierIs",
       "name": "verifierIs",
       "kind": "function",
       "sig": "function verifierIs(read: KeychainRead, verifier: string): boolean",
       "file": "service/device-admin.ts",
       "line": 22,
       "concept": "service.pairing",
       "tests": []
      },
      {
       "id": "local:orchestra:service/device-admin.ts#sameRecord",
       "name": "sameRecord",
       "kind": "function",
       "sig": "function sameRecord(left: DeviceRecord | null, right: DeviceRecord): boolean",
       "file": "service/device-admin.ts",
       "line": 26,
       "concept": "service.pairing",
       "tests": []
      },
      {
       "id": "local:orchestra:service/device-admin.ts#DeviceAdministrator",
       "name": "DeviceAdministrator",
       "kind": "class",
       "sig": "class DeviceAdministrator",
       "file": "service/device-admin.ts",
       "line": 42,
       "concept": "service.pairing",
       "tests": [
        "local device administrator is a mode-0600 Unix capability with no remote-router dependency",
        "auth.test.ts",
        "device-admin.test.ts",
        "initial issue cleanup failure leaves an explicit tombstone without credential material",
        "initial issue re-reads reported Keychain failures and distinguishes landed missing and indeterminate verifiers",
        "a compensating remove that mutates then reports failure clears the recovery marker",
        "mutate-then-fail registry writes are reconciled at issue rotate and revoke commit points",
        "registry failures before transition commit leave old state, while later failures leave durable fail-closed recovery",
        "post-commit audit throw and append-then-throw preserve rotate credentials and completed revokes with durable replay",
        "pair issuance audit failure discards the undisclosed in-memory pairing",
        "real persisted recovery and audit markers survive reload without tokens verifiers or paths",
        "restart recovery tombstones interrupted issue rotate and revoke states and retries Keychain cleanup",
        "an invalid label leaves no pairing Keychain verifier registry transition or audit record",
        "only canonical labels persist and a hand-edited registry label canary fails closed on load",
        "full Lane 2 read matrix uses live per-device auth and rejects missing wrong rotated and revoked credentials",
        "real device rotation and revocation invalidate delayed authenticated detail before egress"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:service/admin-socket.ts#startAdminSocket",
       "local:orchestra:service/admin-socket.ts#assertInertDirectory"
      ],
      [
       "local:orchestra:service/admin-socket.ts#startAdminSocket",
       "local:orchestra:service/admin-socket.ts#inDirectory"
      ],
      [
       "local:orchestra:service/device-admin.ts#DeviceAdministrator",
       "local:orchestra:service/device-admin.ts#sameRecord"
      ],
      [
       "local:orchestra:service/device-admin.ts#DeviceAdministrator",
       "local:orchestra:service/device-admin.ts#verifierIs"
      ]
     ],
     "callsOut": [
      "service.auth",
      "service.registry"
     ]
    },
    {
     "id": "service.registry",
     "name": "Device registry",
     "summary": "Mode-0600 metadata for paired devices and their token generations.",
     "files": [
      "service/registry.ts"
     ],
     "tests": [
      {
       "file": "service/registry.test.ts",
       "cases": 9
      },
      {
       "file": "service/registry-postrename.test.ts",
       "cases": 9
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/registry.ts#fileIdentity",
       "name": "fileIdentity",
       "kind": "function",
       "sig": "function fileIdentity(info: Stats): FileIdentity",
       "file": "service/registry.ts",
       "line": 25,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#sameIdentity",
       "name": "sameIdentity",
       "kind": "function",
       "sig": "function sameIdentity(left: FileIdentity, right: FileIdentity): boolean",
       "file": "service/registry.ts",
       "line": 26,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#DirectoryCustody",
       "name": "DirectoryCustody",
       "kind": "class",
       "sig": "class DirectoryCustody",
       "file": "service/registry.ts",
       "line": 31,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#secureDirectory",
       "name": "secureDirectory",
       "kind": "function",
       "sig": "async function secureDirectory(directory: string, store: string, hook?: CustodyHook): Promise<DirectoryCustody>",
       "file": "service/registry.ts",
       "line": 74,
       "concept": "service.registry",
       "tests": [
        "socket-for-socket overwrite before observation is refused and never adopted or removed",
        "a transient swap around the audit O_CREAT creates the file only inside the held directory",
        "a transient swap around registry temporary creation persists only inside the held directory",
        "a swap inside the intercepted ${store} create call creates only inside the held directory",
        "registry cleanup never removes a replacement at its temporary name",
        "unhooked flipper during audit appends and registry puts creates nothing outside the held directory",
        "admin rollback after the bound admin.sock is replaced keeps the replacement and leaves no staging directory",
        "admin rollback after the bound admin.sock is replaced before its identity is read keeps the replacement",
        "admin success path creates admin.sock exclusively at 0600 and never links, chmods or stages by name",
        "an existing entry at admin.sock refuses the bind atomically and is untouched",
        "shutdown after admin.sock is replaced keeps the replacement; libuv's close-time unlink is inert",
        "shutdown never invokes named unlink even after the final socket observation",
        "registry promotion of a replacement after the final identity check is detected and fails closed",
        "registry interruption preserves the failed temporary and latches custody uncertainty",
        "unhooked registry racer: every promotion or deletion the product performs is reported as drift",
        "unhooked admin.sock racer: no named deletion or staging directory",
        "registry-postrename.test.ts"
       ]
      },
      {
       "id": "local:orchestra:service/registry.ts#statsIdentity",
       "name": "statsIdentity",
       "kind": "function",
       "sig": "function statsIdentity(info: Stats): FileIdentity",
       "file": "service/registry.ts",
       "line": 96,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#CustodyDriftError",
       "name": "CustodyDriftError",
       "kind": "class",
       "sig": "class CustodyDriftError extends Error",
       "file": "service/registry.ts",
       "line": 102,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#sameFileIdentity",
       "name": "sameFileIdentity",
       "kind": "function",
       "sig": "function sameFileIdentity(left: FileIdentity, right: FileIdentity): boolean",
       "file": "service/registry.ts",
       "line": 105,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#deviceLabel",
       "name": "deviceLabel",
       "kind": "function",
       "sig": "function deviceLabel(value: unknown): string | null",
       "file": "service/registry.ts",
       "line": 143,
       "concept": "service.registry",
       "tests": [
        "device labels accept ordinary phone names and reject every path secret control and token canary"
       ]
      },
      {
       "id": "local:orchestra:service/registry.ts#exactKeys",
       "name": "exactKeys",
       "kind": "function",
       "sig": "function exactKeys(row: Record<string, unknown>, allowed: Set<string>): boolean",
       "file": "service/registry.ts",
       "line": 152,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#finiteOrNull",
       "name": "finiteOrNull",
       "kind": "function",
       "sig": "function finiteOrNull(value: unknown): value is number | null",
       "file": "service/registry.ts",
       "line": 156,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#rebuildAudit",
       "name": "rebuildAudit",
       "kind": "function",
       "sig": "function rebuildAudit(value: unknown): PendingDeviceAudit | null | undefined",
       "file": "service/registry.ts",
       "line": 160,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#rebuildRecord",
       "name": "rebuildRecord",
       "kind": "function",
       "sig": "function rebuildRecord(value: unknown): StoredDeviceRecord | null",
       "file": "service/registry.ts",
       "line": 171,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#secureExistingFile",
       "name": "secureExistingFile",
       "kind": "function",
       "sig": "async function secureExistingFile(file: string, custody?: DirectoryCustody)",
       "file": "service/registry.ts",
       "line": 202,
       "concept": "service.registry",
       "tests": []
      },
      {
       "id": "local:orchestra:service/registry.ts#DeviceRegistry",
       "name": "DeviceRegistry",
       "kind": "class",
       "sig": "class DeviceRegistry",
       "file": "service/registry.ts",
       "line": 229,
       "concept": "service.registry",
       "tests": [
        "local device administrator is a mode-0600 Unix capability with no remote-router dependency",
        "audit and registry refuse a symlinked or non-directory parent without chmodding or writing through it",
        "auth.test.ts",
        "registry persistence and audit rotation serialize concurrent writers",
        "atomic overwrite at old registry cleanup unlink preserves the victim and latches subsequent writes",
        "atomic overwrite of an abandoned registry temporary after its last observation preserves memory and refuses writes",
        "a transient swap around registry temporary creation persists only inside the held directory",
        "a swap inside the intercepted ${store} create call creates only inside the held directory",
        "registry cleanup never removes a replacement at its temporary name",
        "unhooked flipper during audit appends and registry puts creates nothing outside the held directory",
        "registry promotion of a replacement after the final identity check is detected and fails closed",
        "registry interruption preserves the failed temporary and latches custody uncertainty",
        "unhooked registry racer: every promotion or deletion the product performs is reported as drift",
        "real persisted recovery and audit markers survive reload without tokens verifiers or paths",
        "only canonical labels persist and a hand-edited registry label canary fails closed on load",
        "registry-postrename.test.ts",
        "genuinely landed inode after reported ${stage} error (${variant})",
        "registry rebuilds exact allowlisted records and rejects secret token and path keys on load and put",
        "registry rejects non-finite numeric fields from put and parsed JSON",
        "registry corrects a safe current-user regular file from 0644 to 0600",
        "registry rejects hard links on load without accepting bytes or changing custody or memory",
        "registry rejects hard links before put or update changes memory or creates a replacement",
        "registry never follows symlinks and rejects non-regular targets",
        "registry persistence is atomic and preserves valid behavior after a failed put",
        "loading an absent registry clears speculative or stale in-memory state",
        "concurrent atomic replacements are always complete parseable allowlisted documents",
        "full Lane 2 read matrix uses live per-device auth and rejects missing wrong rotated and revoked credentials",
        "real device rotation and revocation invalidate delayed authenticated detail before egress"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#CustodyDriftError"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#exactKeys"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#fileIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#rebuildRecord"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#sameIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#secureDirectory"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#secureExistingFile"
      ],
      [
       "local:orchestra:service/registry.ts#DeviceRegistry",
       "local:orchestra:service/registry.ts#statsIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#DirectoryCustody",
       "local:orchestra:service/registry.ts#fileIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#DirectoryCustody",
       "local:orchestra:service/registry.ts#sameIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#rebuildAudit",
       "local:orchestra:service/registry.ts#exactKeys"
      ],
      [
       "local:orchestra:service/registry.ts#rebuildRecord",
       "local:orchestra:service/registry.ts#deviceLabel"
      ],
      [
       "local:orchestra:service/registry.ts#rebuildRecord",
       "local:orchestra:service/registry.ts#exactKeys"
      ],
      [
       "local:orchestra:service/registry.ts#rebuildRecord",
       "local:orchestra:service/registry.ts#finiteOrNull"
      ],
      [
       "local:orchestra:service/registry.ts#rebuildRecord",
       "local:orchestra:service/registry.ts#rebuildAudit"
      ],
      [
       "local:orchestra:service/registry.ts#sameFileIdentity",
       "local:orchestra:service/registry.ts#sameIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#secureDirectory",
       "local:orchestra:service/registry.ts#DirectoryCustody"
      ],
      [
       "local:orchestra:service/registry.ts#secureDirectory",
       "local:orchestra:service/registry.ts#fileIdentity"
      ],
      [
       "local:orchestra:service/registry.ts#statsIdentity",
       "local:orchestra:service/registry.ts#fileIdentity"
      ]
     ],
     "callsOut": [
      "core.safety"
     ]
    },
    {
     "id": "service.auth",
     "name": "Bearer auth",
     "summary": "Per-device bearer tokens verified against secrets held in the Keychain.",
     "files": [
      "service/auth.ts",
      "service/keychain.ts"
     ],
     "tests": [
      {
       "file": "service/auth.test.ts",
       "cases": 11
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/auth.ts#headerValues",
       "name": "headerValues",
       "kind": "function",
       "sig": "function headerValues(request: IncomingMessage, name: string): string[]",
       "file": "service/auth.ts",
       "line": 9,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/auth.ts#newDeviceId",
       "name": "newDeviceId",
       "kind": "function",
       "sig": "function newDeviceId(): string",
       "file": "service/auth.ts",
       "line": 17,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/auth.ts#newDeviceToken",
       "name": "newDeviceToken",
       "kind": "function",
       "sig": "function newDeviceToken(deviceId: string, generation: number): string",
       "file": "service/auth.ts",
       "line": 18,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/auth.ts#parseDeviceToken",
       "name": "parseDeviceToken",
       "kind": "function",
       "sig": "function parseDeviceToken(token: string): { deviceId: string; generation: number } | null",
       "file": "service/auth.ts",
       "line": 23,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/auth.ts#DeviceAuthorizer",
       "name": "DeviceAuthorizer",
       "kind": "class",
       "sig": "class DeviceAuthorizer",
       "file": "service/auth.ts",
       "line": 30,
       "concept": "service.auth",
       "tests": [
        "missing wrong valid revoked and rotated device tokens fail closed within one authorization",
        "concurrent rotate and revoke are serialized and can never resurrect a revoked device",
        "authorization rejects a token when device generation changes during the Keychain read",
        "Keychain failures and recovery never fall back to registry metadata",
        "server.test.ts",
        "full Lane 2 read matrix uses live per-device auth and rejects missing wrong rotated and revoked credentials",
        "real device rotation and revocation invalidate delayed authenticated detail before egress"
       ]
      },
      {
       "id": "local:orchestra:service/keychain.ts#execSecurity",
       "name": "execSecurity",
       "kind": "function",
       "sig": "const execSecurity: SecurityExec = (file, args, timeoutMs) =>",
       "file": "service/keychain.ts",
       "line": 26,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/keychain.ts#validId",
       "name": "validId",
       "kind": "function",
       "sig": "function validId(deviceId: string): boolean",
       "file": "service/keychain.ts",
       "line": 37,
       "concept": "service.auth",
       "tests": []
      },
      {
       "id": "local:orchestra:service/keychain.ts#MacKeychainStore",
       "name": "MacKeychainStore",
       "kind": "class",
       "sig": "class MacKeychainStore implements KeychainStore",
       "file": "service/keychain.ts",
       "line": 41,
       "concept": "service.auth",
       "tests": [
        "Mac Keychain adapter uses fixed argv and fails closed for missing locked corrupt unexpected timeout and recovery",
        "Mac Keychain write and remove reject unexpected output timeout and recover with fixed argv"
       ]
      },
      {
       "id": "local:orchestra:service/keychain.ts#tokenVerifier",
       "name": "tokenVerifier",
       "kind": "function",
       "sig": "function tokenVerifier(token: string): string",
       "file": "service/keychain.ts",
       "line": 80,
       "concept": "service.auth",
       "tests": [
        "registry and audit are mode 0600, content-free, structurally allowlisted, and contain no credential canaries",
        "reported Keychain rotate failure rolls forward only for the new verifier and rolls back only for the old verifier",
        "real persisted recovery and audit markers survive reload without tokens verifiers or paths",
        "server.test.ts"
       ]
      },
      {
       "id": "local:orchestra:service/keychain.ts#verifierMatches",
       "name": "verifierMatches",
       "kind": "function",
       "sig": "function verifierMatches(expected: string, token: string): boolean",
       "file": "service/keychain.ts",
       "line": 84,
       "concept": "service.auth",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:service/auth.ts#DeviceAuthorizer",
       "local:orchestra:service/auth.ts#headerValues"
      ],
      [
       "local:orchestra:service/auth.ts#DeviceAuthorizer",
       "local:orchestra:service/auth.ts#parseDeviceToken"
      ],
      [
       "local:orchestra:service/auth.ts#DeviceAuthorizer",
       "local:orchestra:service/keychain.ts#verifierMatches"
      ],
      [
       "local:orchestra:service/keychain.ts#MacKeychainStore",
       "local:orchestra:service/keychain.ts#validId"
      ],
      [
       "local:orchestra:service/keychain.ts#verifierMatches",
       "local:orchestra:service/keychain.ts#tokenVerifier"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "service.audit",
     "name": "Audit log",
     "summary": "Content-free JSONL audit with the caller's Tailscale identity.",
     "files": [
      "service/audit.ts",
      "service/identity.ts"
     ],
     "tests": [
      {
       "file": "service/audit.test.ts",
       "cases": 7
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/audit.ts#safe",
       "name": "safe",
       "kind": "function",
       "sig": "function safe(record: AuditRecord): AuditRecord",
       "file": "service/audit.ts",
       "line": 29,
       "concept": "service.audit",
       "tests": []
      },
      {
       "id": "local:orchestra:service/audit.ts#openAuditFile",
       "name": "openAuditFile",
       "kind": "function",
       "sig": "async function openAuditFile(file: string, custody: DirectoryCustody)",
       "file": "service/audit.ts",
       "line": 48,
       "concept": "service.audit",
       "tests": []
      },
      {
       "id": "local:orchestra:service/audit.ts#AuditLog",
       "name": "AuditLog",
       "kind": "class",
       "sig": "class AuditLog",
       "file": "service/audit.ts",
       "line": 76,
       "concept": "service.audit",
       "tests": [
        "local device administrator is a mode-0600 Unix capability with no remote-router dependency",
        "audit creates a mode-0600 file and corrects a safe current-user 0644 regular file",
        "audit never follows a file symlink, including a dangling one, and leaves the target untouched",
        "audit rejects directory FIFO and hard-linked paths without writing or chmodding them",
        "audit rejects a wrong-owner file or directory without mutating it",
        "audit and registry refuse a symlinked or non-directory parent without chmodding or writing through it",
        "audit descriptor rotation stays content-free and preserves expired files for local recovery",
        "concurrent audit writers on one path append complete lines across rotation",
        "auth.test.ts",
        "atomic overwrite after old audit rotation link never reaches named unlink",
        "audit truncation is descriptor-owned when the active name is atomically overwritten",
        "expired audit entry is never inspected then unlinked even if atomically replaced in that window",
        "a transient swap around the audit O_CREAT creates the file only inside the held directory",
        "a swap inside the intercepted ${store} create call creates only inside the held directory",
        "unhooked flipper during audit appends and registry puts creates nothing outside the held directory",
        "full Lane 2 read matrix uses live per-device auth and rejects missing wrong rotated and revoked credentials",
        "real device rotation and revocation invalidate delayed authenticated detail before egress"
       ]
      },
      {
       "id": "local:orchestra:service/audit.ts#opaquePeerKey",
       "name": "opaquePeerKey",
       "kind": "function",
       "sig": "function opaquePeerKey(value: string): string",
       "file": "service/audit.ts",
       "line": 143,
       "concept": "service.audit",
       "tests": []
      },
      {
       "id": "local:orchestra:service/identity.ts#rawValues",
       "name": "rawValues",
       "kind": "function",
       "sig": "function rawValues(request: IncomingMessage, name: string): string[]",
       "file": "service/identity.ts",
       "line": 12,
       "concept": "service.audit",
       "tests": []
      },
      {
       "id": "local:orchestra:service/identity.ts#HeaderTailnetIdentityProvider",
       "name": "HeaderTailnetIdentityProvider",
       "kind": "class",
       "sig": "class HeaderTailnetIdentityProvider implements TailnetIdentityProvider",
       "file": "service/identity.ts",
       "line": 20,
       "concept": "service.audit",
       "tests": [
        "Tailscale identity is bounded audit-only across absent duplicate corrupt timeout and recovery",
        "forged Tailscale identities never create fresh IP rate buckets"
       ]
      },
      {
       "id": "local:orchestra:service/identity.ts#boundedIdentity",
       "name": "boundedIdentity",
       "kind": "function",
       "sig": "async function boundedIdentity(provider: TailnetIdentityProvider, request: IncomingMessage, timeoutMs = 250): Promise<IdentityObservation>",
       "file": "service/identity.ts",
       "line": 35,
       "concept": "service.audit",
       "tests": [
        "Tailscale identity is bounded audit-only across absent duplicate corrupt timeout and recovery"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:service/audit.ts#AuditLog",
       "local:orchestra:service/audit.ts#openAuditFile"
      ],
      [
       "local:orchestra:service/audit.ts#AuditLog",
       "local:orchestra:service/audit.ts#safe"
      ],
      [
       "local:orchestra:service/identity.ts#HeaderTailnetIdentityProvider",
       "local:orchestra:service/identity.ts#rawValues"
      ]
     ],
     "callsOut": [
      "core.safety",
      "service.registry"
     ]
    },
    {
     "id": "service.tailscale",
     "name": "Tailscale exposure",
     "summary": "Plans the Tailscale Serve command and checks the installed CLI.",
     "files": [
      "service/tailscale.ts"
     ],
     "tests": [
      {
       "file": "service/tailscale.test.ts",
       "cases": 7
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:service/tailscale.ts#execFixed",
       "name": "execFixed",
       "kind": "function",
       "sig": "const execFixed: FixedExec = (file, args) =>",
       "file": "service/tailscale.ts",
       "line": 27,
       "concept": "service.tailscale",
       "tests": []
      },
      {
       "id": "local:orchestra:service/tailscale.ts#validatedPort",
       "name": "validatedPort",
       "kind": "function",
       "sig": "function validatedPort(port: number, name: string): number",
       "file": "service/tailscale.ts",
       "line": 31,
       "concept": "service.tailscale",
       "tests": []
      },
      {
       "id": "local:orchestra:service/tailscale.ts#tailscaleReadCommands",
       "name": "tailscaleReadCommands",
       "kind": "function",
       "sig": "function tailscaleReadCommands(bin = DEFAULT_TAILSCALE_BIN): readonly FixedCommand[]",
       "file": "service/tailscale.ts",
       "line": 36,
       "concept": "service.tailscale",
       "tests": []
      },
      {
       "id": "local:orchestra:service/tailscale.ts#tailscaleServeCommand",
       "name": "tailscaleServeCommand",
       "kind": "function",
       "sig": "function tailscaleServeCommand(servicePort: number, httpsPort: number, bin = DEFAULT_TAILSCALE_BIN): FixedCommand",
       "file": "service/tailscale.ts",
       "line": 45,
       "concept": "service.tailscale",
       "tests": [
        "tailscale_stub_preserves_single_api_prefix with the reviewed 8443 root proxy",
        "Serve and service ports are explicit and validated"
       ]
      },
      {
       "id": "local:orchestra:service/tailscale.ts#record",
       "name": "record",
       "kind": "function",
       "sig": "const record = (value: unknown): Record<string, unknown> =>",
       "file": "service/tailscale.ts",
       "line": 51,
       "concept": "service.tailscale",
       "tests": []
      },
      {
       "id": "local:orchestra:service/tailscale.ts#exactServeRoute",
       "name": "exactServeRoute",
       "kind": "function",
       "sig": "function exactServeRoute(serve: unknown, dnsName: string | null, httpsPort: number, target: string): boolean",
       "file": "service/tailscale.ts",
       "line": 53,
       "concept": "service.tailscale",
       "tests": []
      },
      {
       "id": "local:orchestra:service/tailscale.ts#preflightTailscale",
       "name": "preflightTailscale",
       "kind": "function",
       "sig": "async function preflightTailscale(servicePort: number, httpsPort: number, exec: FixedExec = execFixed, bin = DEFAULT_TAILSCALE_BIN): Promise<TailscalePreflight>",
       "file": "service/tailscale.ts",
       "line": 71,
       "concept": "service.tailscale",
       "tests": [
        "Serve and service ports are explicit and validated",
        "preflight executes only the three read-only command shapes",
        "8443 Orchestra root can coexist with an unrelated 443 handler",
        "tailscale_public_or_mismatched_route_fails_readiness",
        "preflight rejects public Funnel exposure even with the exact 8443 Serve route"
       ]
      },
      {
       "id": "local:orchestra:service/tailscale.ts#forwardedPath",
       "name": "forwardedPath",
       "kind": "function",
       "sig": "function forwardedPath(publicPath: string): string",
       "file": "service/tailscale.ts",
       "line": 96,
       "concept": "service.tailscale",
       "tests": [
        "tailscale_stub_preserves_single_api_prefix with the reviewed 8443 root proxy"
       ]
      },
      {
       "id": "local:orchestra:service/tailscale.ts#createInstallPlan",
       "name": "createInstallPlan",
       "kind": "function",
       "sig": "function createInstallPlan(node: string, entrypoint: string, tailscaleBin: string, servicePort: number, httpsPort: number): InstallPlan",
       "file": "service/tailscale.ts",
       "line": 102,
       "concept": "service.tailscale",
       "tests": [
        "installer plan separates read-only preflight from the sole deferred 8443 mutation"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:service/tailscale.ts#createInstallPlan",
       "local:orchestra:service/tailscale.ts#tailscaleReadCommands"
      ],
      [
       "local:orchestra:service/tailscale.ts#createInstallPlan",
       "local:orchestra:service/tailscale.ts#tailscaleServeCommand"
      ],
      [
       "local:orchestra:service/tailscale.ts#exactServeRoute",
       "local:orchestra:service/tailscale.ts#record"
      ],
      [
       "local:orchestra:service/tailscale.ts#preflightTailscale",
       "local:orchestra:service/tailscale.ts#exactServeRoute"
      ],
      [
       "local:orchestra:service/tailscale.ts#preflightTailscale",
       "local:orchestra:service/tailscale.ts#record"
      ],
      [
       "local:orchestra:service/tailscale.ts#preflightTailscale",
       "local:orchestra:service/tailscale.ts#tailscaleReadCommands"
      ],
      [
       "local:orchestra:service/tailscale.ts#preflightTailscale",
       "local:orchestra:service/tailscale.ts#validatedPort"
      ],
      [
       "local:orchestra:service/tailscale.ts#tailscaleServeCommand",
       "local:orchestra:service/tailscale.ts#validatedPort"
      ]
     ],
     "callsOut": []
    }
   ]
  },
  {
   "id": "phone",
   "name": "Phone app",
   "summary": "The installable phone preview that pairs once and shows a read-only snapshot.",
   "children": [
    {
     "id": "phone.credentials",
     "name": "Credential custody",
     "summary": "Keeps the device token in IndexedDB and nowhere else.",
     "files": [
      "src/mobile/credential-store.ts"
     ],
     "tests": [
      {
       "file": "src/mobile/credential-store.test.ts",
       "cases": 4
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/mobile/credential-store.ts#database",
       "name": "database",
       "kind": "function",
       "sig": "function database(): Promise<IDBDatabase>",
       "file": "src/mobile/credential-store.ts",
       "line": 16,
       "concept": "phone.credentials",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/credential-store.ts#transaction",
       "name": "transaction",
       "kind": "function",
       "sig": "async function transaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>, signal?: AbortSignal): Promise<T>",
       "file": "src/mobile/credential-store.ts",
       "line": 27,
       "concept": "phone.credentials",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/credential-store.ts#credential",
       "name": "credential",
       "kind": "function",
       "sig": "function credential(value: unknown): DeviceCredential | null",
       "file": "src/mobile/credential-store.ts",
       "line": 66,
       "concept": "phone.credentials",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/credential-store.ts#createCredentialStore",
       "name": "createCredentialStore",
       "kind": "function",
       "sig": "function createCredentialStore(): CredentialStore",
       "file": "src/mobile/credential-store.ts",
       "line": 77,
       "concept": "phone.credentials",
       "tests": [
        "credential writes resolve only when the IndexedDB transaction commits",
        "transaction abort after request success fails credential storage",
        "a newer lifecycle generation can abort an in-flight credential commit",
        "credential reads and deletes also wait for transaction completion"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:src/mobile/credential-store.ts#createCredentialStore",
       "local:orchestra:src/mobile/credential-store.ts#credential"
      ],
      [
       "local:orchestra:src/mobile/credential-store.ts#createCredentialStore",
       "local:orchestra:src/mobile/credential-store.ts#transaction"
      ],
      [
       "local:orchestra:src/mobile/credential-store.ts#transaction",
       "local:orchestra:src/mobile/credential-store.ts#database"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "phone.transport",
     "name": "HTTP transport",
     "summary": "Fetches the snapshot, follows the event stream and validates every response.",
     "files": [
      "src/mobile/http-transport.ts",
      "src/mobile/transport.ts",
      "src/mobile/validate.ts"
     ],
     "tests": [
      {
       "file": "src/mobile/http-transport.test.ts",
       "cases": 25
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#defaultRuntime",
       "name": "defaultRuntime",
       "kind": "function",
       "sig": "function defaultRuntime(): HttpTransportRuntime",
       "file": "src/mobile/http-transport.ts",
       "line": 27,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#compatibleMeta",
       "name": "compatibleMeta",
       "kind": "function",
       "sig": "function compatibleMeta(value: unknown, credential: DeviceCredential): value is MetaResponse",
       "file": "src/mobile/http-transport.ts",
       "line": 39,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#issued",
       "name": "issued",
       "kind": "function",
       "sig": "function issued(value: unknown): value is PairExchangeResponse",
       "file": "src/mobile/http-transport.ts",
       "line": 48,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#json",
       "name": "json",
       "kind": "function",
       "sig": "async function json(response: Response): Promise<{ ok: true; value: unknown } | { ok: false }>",
       "file": "src/mobile/http-transport.ts",
       "line": 55,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#retryAfter",
       "name": "retryAfter",
       "kind": "function",
       "sig": "function retryAfter(response: Response): number",
       "file": "src/mobile/http-transport.ts",
       "line": 60,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "name": "createHttpTransport",
       "kind": "function",
       "sig": "function createHttpTransport(store: CredentialStore, runtime: HttpTransportRuntime = defaultRuntime()): AuthenticatedMobileTransport",
       "file": "src/mobile/http-transport.ts",
       "line": 66,
       "concept": "phone.transport",
       "tests": [
        "authenticated snapshot reads send the bearer only in Authorization and reuse an exact ETag",
        "mount snapshot and SSE revision share one delayed metadata check",
        "a failed shared metadata check is cleared so the generation can retry",
        "pairing invalidates an in-flight metadata check before the new generation reads",
        "close invalidates and aborts an in-flight metadata check",
        "missing, wrong, revoked and rotated credentials fail closed and are cleared",
        "pair exchange handles success, expiry or replay, rate limit, incompatibility and network loss",
        "incompatible and malformed responses never replace the last good snapshot",
        "revision-only SSE triggers a conditional fetch and reconnect is bounded",
        "an incompatible event stream stops without being relabelled as reconnecting",
        "an SSE-triggered 401 advances the generation and still reports access ended",
        "sleep and wake aborts the old stream, fetches current state and reconnects",
        "thread reads are side-effect-free GETs and shutdown removes listeners and aborts SSE",
        "strict nested validation rejects malformed remote fields and preserves last-good state",
        "detail validation rejects malformed fields and a returned id different from the request",
        "an old-read 401 interleaved with pair save cannot erase the new credential",
        "close during pair save aborts the credential before commit",
        "a newer overlapping pair aborts the older save and only its credential commits",
        "the credential being replaced cannot authorize a same-generation read",
        "close during credential loading starts no request or stream",
        "bounded request deadlines and SSE silence watchdog recover honestly",
        "deadlines cover stalled Snapshot and detail response bodies",
        "429 is reported distinctly and Retry-After is bounded",
        "once-per-second revisions keep reading beyond seventy seconds without exhausting buckets"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#object",
       "name": "object",
       "kind": "function",
       "sig": "const object = (value: unknown): value is ObjectValue =>",
       "file": "src/mobile/validate.ts",
       "line": 6,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#finite",
       "name": "finite",
       "kind": "function",
       "sig": "const finite: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 7,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#integer",
       "name": "integer",
       "kind": "function",
       "sig": "const integer = (min = 0, max = Number.MAX_SAFE_INTEGER): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 8,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#boolean",
       "name": "boolean",
       "kind": "function",
       "sig": "const boolean: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 9,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#string",
       "name": "string",
       "kind": "function",
       "sig": "const string = (max: number, pattern?: RegExp): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 10,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#nullable",
       "name": "nullable",
       "kind": "function",
       "sig": "const nullable = (check: Check): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 11,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#optional",
       "name": "optional",
       "kind": "function",
       "sig": "const optional = (check: Check): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 12,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#enumeration",
       "name": "enumeration",
       "kind": "function",
       "sig": "const enumeration = (...values: readonly string[]): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 13,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#array",
       "name": "array",
       "kind": "function",
       "sig": "const array = (check: Check, max: number): Check =>",
       "file": "src/mobile/validate.ts",
       "line": 14,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#shape",
       "name": "shape",
       "kind": "function",
       "sig": "function shape(value: unknown, required: Record<string, Check>, optionalFields: Record<string, Check> = {}): value is ObjectValue",
       "file": "src/mobile/validate.ts",
       "line": 16,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#safeState",
       "name": "safeState",
       "kind": "function",
       "sig": "const safeState: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 29,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#sourceStatus",
       "name": "sourceStatus",
       "kind": "function",
       "sig": "const sourceStatus: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 31,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#quotaWindow",
       "name": "quotaWindow",
       "kind": "function",
       "sig": "const quotaWindow: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 42,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#quotaChip",
       "name": "quotaChip",
       "kind": "function",
       "sig": "const quotaChip: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 50,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#observedCap",
       "name": "observedCap",
       "kind": "function",
       "sig": "const observedCap: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 56,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#quotaRow",
       "name": "quotaRow",
       "kind": "function",
       "sig": "const quotaRow: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 62,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#messageEntry",
       "name": "messageEntry",
       "kind": "function",
       "sig": "const messageEntry: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 69,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#messageLink",
       "name": "messageLink",
       "kind": "function",
       "sig": "const messageLink: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 73,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#messageThread",
       "name": "messageThread",
       "kind": "function",
       "sig": "const messageThread: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 84,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#cliCall",
       "name": "cliCall",
       "kind": "function",
       "sig": "const cliCall: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 93,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#subagent",
       "name": "subagent",
       "kind": "function",
       "sig": "const subagent: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 98,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "name": "backgroundTask",
       "kind": "function",
       "sig": "const backgroundTask: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 104,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#taskRun",
       "name": "taskRun",
       "kind": "function",
       "sig": "const taskRun: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 109,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#taskGroup",
       "name": "taskGroup",
       "kind": "function",
       "sig": "const taskGroup: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 115,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#cliRun",
       "name": "cliRun",
       "kind": "function",
       "sig": "const cliRun: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 119,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#cliRuns",
       "name": "cliRuns",
       "kind": "function",
       "sig": "const cliRuns: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 123,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#goal",
       "name": "goal",
       "kind": "function",
       "sig": "const goal: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 127,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#mission",
       "name": "mission",
       "kind": "function",
       "sig": "const mission: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 133,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#blocker",
       "name": "blocker",
       "kind": "function",
       "sig": "const blocker: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 145,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#lane",
       "name": "lane",
       "kind": "function",
       "sig": "const lane: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 150,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#overview",
       "name": "overview",
       "kind": "function",
       "sig": "const overview: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 156,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#pullRequest",
       "name": "pullRequest",
       "kind": "function",
       "sig": "const pullRequest: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 162,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#lead",
       "name": "lead",
       "kind": "function",
       "sig": "const lead: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 169,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#orchestrator",
       "name": "orchestrator",
       "kind": "function",
       "sig": "const orchestrator: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 182,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#needsJv",
       "name": "needsJv",
       "kind": "function",
       "sig": "const needsJv: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 188,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#sources",
       "name": "sources",
       "kind": "function",
       "sig": "const sources: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 195,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#taskHistory",
       "name": "taskHistory",
       "kind": "function",
       "sig": "const taskHistory: Check = (value) =>",
       "file": "src/mobile/validate.ts",
       "line": 199,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#validMobileSnapshot",
       "name": "validMobileSnapshot",
       "kind": "function",
       "sig": "function validMobileSnapshot(value: unknown): value is MobileSnapshot",
       "file": "src/mobile/validate.ts",
       "line": 202,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#validMessageDetail",
       "name": "validMessageDetail",
       "kind": "function",
       "sig": "function validMessageDetail(value: unknown, expectedId: string): value is MessageDetailResponse",
       "file": "src/mobile/validate.ts",
       "line": 210,
       "concept": "phone.transport",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/validate.ts#mobileMessageLinkForTest",
       "name": "mobileMessageLinkForTest",
       "kind": "function",
       "sig": "const mobileMessageLinkForTest = (value: unknown): value is MobileMessageLink =>",
       "file": "src/mobile/validate.ts",
       "line": 214,
       "concept": "phone.transport",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/http-transport.ts#compatibleMeta"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/http-transport.ts#defaultRuntime"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/http-transport.ts#issued"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/http-transport.ts#json"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/http-transport.ts#retryAfter"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/validate.ts#validMessageDetail"
      ],
      [
       "local:orchestra:src/mobile/http-transport.ts#createHttpTransport",
       "local:orchestra:src/mobile/validate.ts#validMobileSnapshot"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#backgroundTask",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#blocker",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#blocker",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#blocker",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#blocker",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliCall",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliCall",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliCall",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliCall",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliRun",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliRun",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliRun",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliRuns",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#cliRuns",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#goal",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#goal",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#goal",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#goal",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#goal",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lane",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lane",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lane",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lead",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lead",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lead",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lead",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#lead",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageEntry",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageEntry",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageLink",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageLink",
       "local:orchestra:src/mobile/validate.ts#optional"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageLink",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageLink",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#messageThread",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#object"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mission",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#mobileMessageLinkForTest",
       "local:orchestra:src/mobile/validate.ts#messageLink"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#needsJv",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#needsJv",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#needsJv",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#needsJv",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#observedCap",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#observedCap",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#observedCap",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#orchestrator",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#orchestrator",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#orchestrator",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#orchestrator",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#overview",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#overview",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#overview",
       "local:orchestra:src/mobile/validate.ts#optional"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#overview",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#overview",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#pullRequest",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#pullRequest",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#pullRequest",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#pullRequest",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#pullRequest",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaChip",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaChip",
       "local:orchestra:src/mobile/validate.ts#optional"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaChip",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaChip",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaRow",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaRow",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaRow",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaRow",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaWindow",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaWindow",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaWindow",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#quotaWindow",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#shape",
       "local:orchestra:src/mobile/validate.ts#object"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sourceStatus",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sourceStatus",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sourceStatus",
       "local:orchestra:src/mobile/validate.ts#optional"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sourceStatus",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sources",
       "local:orchestra:src/mobile/validate.ts#object"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#sources",
       "local:orchestra:src/mobile/validate.ts#sourceStatus"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#subagent",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#subagent",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#subagent",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskGroup",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskGroup",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskHistory",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskRun",
       "local:orchestra:src/mobile/validate.ts#enumeration"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskRun",
       "local:orchestra:src/mobile/validate.ts#integer"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskRun",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskRun",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#taskRun",
       "local:orchestra:src/mobile/validate.ts#string"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#validMessageDetail",
       "local:orchestra:src/mobile/validate.ts#shape"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#validMobileSnapshot",
       "local:orchestra:src/mobile/validate.ts#array"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#validMobileSnapshot",
       "local:orchestra:src/mobile/validate.ts#nullable"
      ],
      [
       "local:orchestra:src/mobile/validate.ts#validMobileSnapshot",
       "local:orchestra:src/mobile/validate.ts#shape"
      ]
     ],
     "callsOut": []
    },
    {
     "id": "phone.views",
     "name": "Phone views",
     "summary": "Pairing screen, needs-JV list and lead views for a small screen.",
     "files": [
      "src/mobile/main.tsx",
      "src/mobile/MobileApp.tsx",
      "src/mobile/views.tsx",
      "src/mobile/state.ts",
      "src/mobile/vite.config.ts"
     ],
     "tests": [
      {
       "file": "src/mobile/mobile.test.ts",
       "cases": 20
      }
     ],
     "symbols": [
      {
       "id": "local:orchestra:src/mobile/MobileApp.tsx#detailHasAdvanced",
       "name": "detailHasAdvanced",
       "kind": "function",
       "sig": "const detailHasAdvanced = ( summary: { updatedAt: number; messageCount: number }, detail: { updatedAt: number; messageCount: number }, ) =>",
       "file": "src/mobile/MobileApp.tsx",
       "line": 6,
       "concept": "phone.views",
       "tests": [
        "a newer summary never shows obsolete needs-you or message count beneath Live"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/MobileApp.tsx#MobileApp",
       "name": "MobileApp",
       "kind": "component",
       "sig": "function MobileApp({ transport, pairing, clock, notice }: { transport: MobileReadTransport; pairing?: MobilePairingTransport; clock: () => number; notice?: string })",
       "file": "src/mobile/MobileApp.tsx",
       "line": 12,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/state.ts#applyRead",
       "name": "applyRead",
       "kind": "function",
       "sig": "function applyRead(state: MobileState, result: MobileReadResult): MobileState",
       "file": "src/mobile/state.ts",
       "line": 15,
       "concept": "phone.views",
       "tests": [
        "mobile.test.ts",
        "a failed read keeps the last view and a good read recovers"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/state.ts#isCredentialFreeHttpsUrl",
       "name": "isCredentialFreeHttpsUrl",
       "kind": "function",
       "sig": "function isCredentialFreeHttpsUrl(value: string): boolean",
       "file": "src/mobile/state.ts",
       "line": 28,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/state.ts#safeThreadLink",
       "name": "safeThreadLink",
       "kind": "function",
       "sig": "function safeThreadLink(links: MobileMessageLink[], target: string): MobileUrlLink | null",
       "file": "src/mobile/state.ts",
       "line": 38,
       "concept": "phone.views",
       "tests": [
        "only allowlisted https links become anchors"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/state.ts#safePrUrl",
       "name": "safePrUrl",
       "kind": "function",
       "sig": "function safePrUrl(url: string): string | null",
       "file": "src/mobile/state.ts",
       "line": 44,
       "concept": "phone.views",
       "tests": [
        "only allowlisted https links become anchors"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#MobileView",
       "name": "MobileView",
       "kind": "component",
       "sig": "function MobileView({ state, now, tab, thread, needsOnly, query, actions, notice, pair, pairingBusy = false, pairingResult = null }: MobileViewProps)",
       "file": "src/mobile/views.tsx",
       "line": 49,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#PairingView",
       "name": "PairingView",
       "kind": "component",
       "sig": "function PairingView({ ended, busy, result, pair }: { ended: boolean; busy: boolean; result: PairResult | null; pair(code: string, label: string): Promise<void> })",
       "file": "src/mobile/views.tsx",
       "line": 88,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#unhealthySources",
       "name": "unhealthySources",
       "kind": "function",
       "sig": "function unhealthySources(snapshot: MobileSnapshot, now: number): [SourceName, SourceStatus][]",
       "file": "src/mobile/views.tsx",
       "line": 110,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#ConnectionLine",
       "name": "ConnectionLine",
       "kind": "component",
       "sig": "function ConnectionLine({ state, now }: { state: MobileState; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 115,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#ConnectionBanner",
       "name": "ConnectionBanner",
       "kind": "component",
       "sig": "function ConnectionBanner({ state, now }: { state: MobileState; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 136,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#snapshotAgeBanner",
       "name": "snapshotAgeBanner",
       "kind": "function",
       "sig": "function snapshotAgeBanner(title: string, body: string, state: MobileState, now: number)",
       "file": "src/mobile/views.tsx",
       "line": 153,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#Section",
       "name": "Section",
       "kind": "component",
       "sig": "function Section({ title, count, meta, children, className = \"\" }: { title: string; count?: number; meta?: React.ReactNode; children: React.ReactNode; className?: string })",
       "file": "src/mobile/views.tsx",
       "line": 157,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#GoalView",
       "name": "GoalView",
       "kind": "component",
       "sig": "function GoalView({ title, priority, goal, blocker }: { title: string; priority: MissionPriority | null; goal: LeadGoal; blocker: string | null })",
       "file": "src/mobile/views.tsx",
       "line": 166,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#NowView",
       "name": "NowView",
       "kind": "component",
       "sig": "function NowView({ snapshot, state, now, actions }: { snapshot: MobileSnapshot; state: MobileState; now: number; actions: ViewActions })",
       "file": "src/mobile/views.tsx",
       "line": 189,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#phonePace",
       "name": "phonePace",
       "kind": "function",
       "sig": "function phonePace(window: QuotaWindow, now: number): keyof typeof cue",
       "file": "src/mobile/views.tsx",
       "line": 255,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#QuotaWindowCell",
       "name": "QuotaWindowCell",
       "kind": "component",
       "sig": "function QuotaWindowCell({ label, window, now }: { label: string; window: QuotaWindow | null; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 262,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#QuotaSection",
       "name": "QuotaSection",
       "kind": "component",
       "sig": "function QuotaSection({ rows, status, now }: { rows: QuotaRow[]; status: SourceStatus; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 278,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#MessagesView",
       "name": "MessagesView",
       "kind": "component",
       "sig": "function MessagesView({ snapshot, now, needsOnly, query, actions }: { snapshot: MobileSnapshot; now: number; needsOnly: boolean; query: string; actions: ViewActions; })",
       "file": "src/mobile/views.tsx",
       "line": 306,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#ThreadDetail",
       "name": "ThreadDetail",
       "kind": "component",
       "sig": "function ThreadDetail({ snapshot, thread, now, onBack }: { snapshot: MobileSnapshot; thread: ThreadView; now: number; onBack(): void })",
       "file": "src/mobile/views.tsx",
       "line": 343,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#linkText",
       "name": "linkText",
       "kind": "function",
       "sig": "function linkText(target: string, label: string): string",
       "file": "src/mobile/views.tsx",
       "line": 385,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#External",
       "name": "External",
       "kind": "component",
       "sig": "function External({ href, className, children }: { href: string; className?: string; children: React.ReactNode })",
       "file": "src/mobile/views.tsx",
       "line": 390,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#SafeLink",
       "name": "SafeLink",
       "kind": "component",
       "sig": "function SafeLink({ links, link }: { links: MobileMessageThread[\"links\"]; link: MobileUrlLink })",
       "file": "src/mobile/views.tsx",
       "line": 395,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#MessageEntryView",
       "name": "MessageEntryView",
       "kind": "component",
       "sig": "function MessageEntryView({ thread, body, author, at, now }: { thread: MobileMessageThread; body: string; author: string; at: number; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 401,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#Inline",
       "name": "Inline",
       "kind": "component",
       "sig": "function Inline({ part, links }: { part: InlinePart; links: MobileMessageThread[\"links\"] })",
       "file": "src/mobile/views.tsx",
       "line": 419,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#LeadsView",
       "name": "LeadsView",
       "kind": "component",
       "sig": "function LeadsView({ snapshot, now }: { snapshot: MobileSnapshot; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 431,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#LeadCardView",
       "name": "LeadCardView",
       "kind": "component",
       "sig": "function LeadCardView({ lead, now }: { lead: Lead; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 440,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#determinateMission",
       "name": "determinateMission",
       "kind": "function",
       "sig": "function determinateMission(mission: Mission | null): mission is DeterminateMission",
       "file": "src/mobile/views.tsx",
       "line": 512,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#MissionView",
       "name": "MissionView",
       "kind": "component",
       "sig": "function MissionView({ mission, now, compact = false, unavailable = false }: { mission: Mission; now: number; compact?: boolean; unavailable?: boolean })",
       "file": "src/mobile/views.tsx",
       "line": 517,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#ActivityView",
       "name": "ActivityView",
       "kind": "component",
       "sig": "function ActivityView({ snapshot, now }: { snapshot: MobileSnapshot; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 531,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#ActivityGroup",
       "name": "ActivityGroup",
       "kind": "component",
       "sig": "function ActivityGroup({ title, count, children }: { title: string; count: number; children: React.ReactNode })",
       "file": "src/mobile/views.tsx",
       "line": 567,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#TaskItem",
       "name": "TaskItem",
       "kind": "component",
       "sig": "function TaskItem({ task, now }: { task: BackgroundTask; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 571,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#CallItem",
       "name": "CallItem",
       "kind": "component",
       "sig": "function CallItem({ call, now }: { call: CliCall; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 581,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/views.tsx#RunItem",
       "name": "RunItem",
       "kind": "component",
       "sig": "function RunItem({ run, now }: { run: TaskRun; now: number })",
       "file": "src/mobile/views.tsx",
       "line": 591,
       "concept": "phone.views",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/vite.config.ts#cspPlugin",
       "name": "cspPlugin",
       "kind": "function",
       "sig": "function cspPlugin(csp: string): Plugin",
       "file": "src/mobile/vite.config.ts",
       "line": 8,
       "concept": "phone.views",
       "tests": []
      }
     ],
     "calls": [
      [
       "local:orchestra:src/mobile/MobileApp.tsx#MobileApp",
       "local:orchestra:src/mobile/MobileApp.tsx#detailHasAdvanced"
      ],
      [
       "local:orchestra:src/mobile/MobileApp.tsx#MobileApp",
       "local:orchestra:src/mobile/state.ts#applyRead"
      ],
      [
       "local:orchestra:src/mobile/MobileApp.tsx#MobileApp",
       "local:orchestra:src/mobile/views.tsx#MobileView"
      ],
      [
       "local:orchestra:src/mobile/state.ts#safePrUrl",
       "local:orchestra:src/mobile/state.ts#isCredentialFreeHttpsUrl"
      ],
      [
       "local:orchestra:src/mobile/state.ts#safeThreadLink",
       "local:orchestra:src/mobile/state.ts#isCredentialFreeHttpsUrl"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ActivityView",
       "local:orchestra:src/mobile/views.tsx#ActivityGroup"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ActivityView",
       "local:orchestra:src/mobile/views.tsx#CallItem"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ActivityView",
       "local:orchestra:src/mobile/views.tsx#RunItem"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ActivityView",
       "local:orchestra:src/mobile/views.tsx#Section"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ActivityView",
       "local:orchestra:src/mobile/views.tsx#TaskItem"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ConnectionBanner",
       "local:orchestra:src/mobile/views.tsx#snapshotAgeBanner"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ConnectionLine",
       "local:orchestra:src/mobile/views.tsx#unhealthySources"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#Inline",
       "local:orchestra:src/mobile/state.ts#safeThreadLink"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#Inline",
       "local:orchestra:src/mobile/views.tsx#External"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#LeadCardView",
       "local:orchestra:src/mobile/state.ts#safePrUrl"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#LeadCardView",
       "local:orchestra:src/mobile/views.tsx#External"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#LeadCardView",
       "local:orchestra:src/mobile/views.tsx#MissionView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#LeadsView",
       "local:orchestra:src/mobile/views.tsx#LeadCardView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MessageEntryView",
       "local:orchestra:src/mobile/views.tsx#Inline"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MessagesView",
       "local:orchestra:src/mobile/views.tsx#Section"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MissionView",
       "local:orchestra:src/mobile/views.tsx#determinateMission"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#ActivityView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#ConnectionBanner"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#ConnectionLine"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#LeadsView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#MessagesView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#NowView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#PairingView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#MobileView",
       "local:orchestra:src/mobile/views.tsx#ThreadDetail"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#GoalView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#MissionView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#QuotaSection"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#Section"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#determinateMission"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#NowView",
       "local:orchestra:src/mobile/views.tsx#unhealthySources"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#QuotaSection",
       "local:orchestra:src/mobile/views.tsx#QuotaWindowCell"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#QuotaSection",
       "local:orchestra:src/mobile/views.tsx#Section"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#QuotaWindowCell",
       "local:orchestra:src/mobile/views.tsx#phonePace"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#SafeLink",
       "local:orchestra:src/mobile/state.ts#safeThreadLink"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#SafeLink",
       "local:orchestra:src/mobile/views.tsx#External"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#SafeLink",
       "local:orchestra:src/mobile/views.tsx#linkText"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#TaskItem",
       "local:orchestra:src/mobile/views.tsx#CallItem"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ThreadDetail",
       "local:orchestra:src/mobile/views.tsx#MessageEntryView"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ThreadDetail",
       "local:orchestra:src/mobile/views.tsx#SafeLink"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#ThreadDetail",
       "local:orchestra:src/mobile/views.tsx#Section"
      ],
      [
       "local:orchestra:src/mobile/views.tsx#linkText",
       "local:orchestra:src/mobile/state.ts#safePrUrl"
      ]
     ],
     "callsOut": [
      "ui.messages",
      "ui.viewmodel"
     ]
    },
    {
     "id": "phone.fixtures",
     "name": "Fixture preview",
     "summary": "A browser-only entry that runs the phone views on canned data.",
     "files": [
      "src/mobile/fixture-main.tsx",
      "src/mobile/fixtures.ts"
     ],
     "tests": [],
     "symbols": [
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#composeFixture",
       "name": "composeFixture",
       "kind": "function",
       "sig": "function composeFixture(): { snapshot: MobileSnapshot; detail: MobileMessageThread }",
       "file": "src/mobile/fixtures.ts",
       "line": 29,
       "concept": "phone.fixtures",
       "tests": [
        "http-transport.test.ts",
        "thread reads are side-effect-free GETs and shutdown removes listeners and aborts SSE",
        "detail validation rejects malformed fields and a returned id different from the request",
        "deadlines cover stalled Snapshot and detail response bodies",
        "the fixture changes only the documented fields of the frozen JSON",
        "a failed read keeps the last view and a good read recovers",
        "every connection state is labelled",
        "exhausted mobile quota retains its usage bar and elapsed-window tick",
        "mobile missions render native progress only for valid determinate progress",
        "a newer summary never shows obsolete needs-you or message count beneath Live",
        "only allowlisted https links become anchors"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#failed",
       "name": "failed",
       "kind": "function",
       "sig": "function failed(status: SourceStatus, error: SourceStatus[\"error\"], lastOkAt: number | null): SourceStatus",
       "file": "src/mobile/fixtures.ts",
       "line": 47,
       "concept": "phone.fixtures",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#scenario",
       "name": "scenario",
       "kind": "function",
       "sig": "function scenario(name: ScenarioName): Scenario",
       "file": "src/mobile/fixtures.ts",
       "line": 51,
       "concept": "phone.fixtures",
       "tests": [
        "mobile.test.ts",
        "exhausted mobile quota retains its usage bar and elapsed-window tick"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#createFixtureTransport",
       "name": "createFixtureTransport",
       "kind": "function",
       "sig": "function createFixtureTransport(name: ScenarioName): MobileReadTransport",
       "file": "src/mobile/fixtures.ts",
       "line": 82,
       "concept": "phone.fixtures",
       "tests": [
        "mobile.test.ts",
        "the fixture transport exposes only the three read methods",
        "watch delivers later results after the first read, and unsubscribe stops it",
        "every connection state is labelled"
       ]
      },
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#createPairingFixtureTransport",
       "name": "createPairingFixtureTransport",
       "kind": "function",
       "sig": "function createPairingFixtureTransport(ended = false): { transport: MobileReadTransport; pairing: MobilePairingTransport }",
       "file": "src/mobile/fixtures.ts",
       "line": 105,
       "concept": "phone.fixtures",
       "tests": []
      },
      {
       "id": "local:orchestra:src/mobile/fixtures.ts#scenarioFromHash",
       "name": "scenarioFromHash",
       "kind": "function",
       "sig": "function scenarioFromHash(hash: string): ScenarioName",
       "file": "src/mobile/fixtures.ts",
       "line": 118,
       "concept": "phone.fixtures",
       "tests": [
        "an unknown #state falls back to live"
       ]
      }
     ],
     "calls": [
      [
       "local:orchestra:src/mobile/fixtures.ts#createFixtureTransport",
       "local:orchestra:src/mobile/fixtures.ts#composeFixture"
      ],
      [
       "local:orchestra:src/mobile/fixtures.ts#createFixtureTransport",
       "local:orchestra:src/mobile/fixtures.ts#scenario"
      ],
      [
       "local:orchestra:src/mobile/fixtures.ts#scenario",
       "local:orchestra:src/mobile/fixtures.ts#composeFixture"
      ],
      [
       "local:orchestra:src/mobile/fixtures.ts#scenario",
       "local:orchestra:src/mobile/fixtures.ts#failed"
      ]
     ],
     "callsOut": []
    }
   ]
  }
 ],
 "externals": [
  {
   "id": "x.aishared",
   "name": "ai-shared CLIs",
   "summary": "subagent-status, lead-agents, ai-quota, msg and ai-route."
  },
  {
   "id": "x.terminal",
   "name": "tmux and iTerm2",
   "summary": "Panes the leads run in, and the terminal app that shows them."
  },
  {
   "id": "x.github",
   "name": "GitHub",
   "summary": "Open pull requests through the gh CLI."
  },
  {
   "id": "x.keychain",
   "name": "macOS Keychain",
   "summary": "Holds each paired device's token secret."
  },
  {
   "id": "x.tailscale",
   "name": "Tailscale",
   "summary": "Serves the loopback service to the tailnet with caller identity."
  }
 ],
 "relationships": [
  {
   "from": "desktop.shell",
   "to": "core.poller",
   "label": "starts",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "core.snapshot",
   "label": "pushes snapshot from",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "core.messages",
   "label": "runs message actions",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "core.runtime",
   "label": "runs on",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.shell",
   "to": "desktop.goto",
   "label": "handles go-to with",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "desktop.messages",
   "label": "handles messages with",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "desktop.summaries",
   "label": "summarises with",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "desktop.adapters",
   "label": "loads core through",
   "basis": "imports"
  },
  {
   "from": "desktop.shell",
   "to": "core.contracts",
   "label": "exposes",
   "basis": "imports"
  },
  {
   "from": "desktop.messages",
   "to": "desktop.goto",
   "label": "jumps with",
   "basis": "imports"
  },
  {
   "from": "desktop.messages",
   "to": "core.messages",
   "label": "validates with",
   "basis": "imports"
  },
  {
   "from": "desktop.goto",
   "to": "core.safety",
   "label": "checks targets with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.goto",
   "to": "core.sources",
   "label": "finds panes with",
   "basis": "imports"
  },
  {
   "from": "desktop.summaries",
   "to": "core.safety",
   "label": "sanitises with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.summaries",
   "to": "core.sources",
   "label": "reads tasks from",
   "basis": "imports"
  },
  {
   "from": "desktop.adapters",
   "to": "core.sources",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.adapters",
   "to": "core.poller",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.adapters",
   "to": "core.snapshot",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.adapters",
   "to": "core.safety",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.adapters",
   "to": "core.contracts",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.adapters",
   "to": "core.runtime",
   "label": "re-exports",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.app",
   "to": "desktop.shell",
   "label": "reads snapshot over IPC",
   "basis": "reading"
  },
  {
   "from": "ui.app",
   "to": "ui.leads",
   "label": "renders",
   "basis": "imports"
  },
  {
   "from": "ui.app",
   "to": "ui.board",
   "label": "renders",
   "basis": "imports"
  },
  {
   "from": "ui.app",
   "to": "ui.messages",
   "label": "renders",
   "basis": "imports"
  },
  {
   "from": "ui.app",
   "to": "ui.quota",
   "label": "renders",
   "basis": "imports"
  },
  {
   "from": "ui.app",
   "to": "ui.viewmodel",
   "label": "derives rows with",
   "basis": "imports"
  },
  {
   "from": "ui.leads",
   "to": "ui.viewmodel",
   "label": "formats with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.leads",
   "to": "ui.collapse",
   "label": "folds with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.board",
   "to": "ui.viewmodel",
   "label": "formats with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.board",
   "to": "ui.collapse",
   "label": "folds with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.board",
   "to": "ui.leads",
   "label": "reuses task list",
   "basis": "imports"
  },
  {
   "from": "ui.messages",
   "to": "ui.viewmodel",
   "label": "formats with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "ui.quota",
   "to": "ui.viewmodel",
   "label": "formats with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.sources",
   "to": "x.aishared",
   "label": "polls",
   "basis": "reading"
  },
  {
   "from": "core.sources",
   "to": "x.github",
   "label": "lists PRs from",
   "basis": "reading"
  },
  {
   "from": "core.sources",
   "to": "x.terminal",
   "label": "lists panes from",
   "basis": "reading"
  },
  {
   "from": "desktop.goto",
   "to": "x.terminal",
   "label": "focuses",
   "basis": "reading"
  },
  {
   "from": "desktop.summaries",
   "to": "x.aishared",
   "label": "asks ai-route",
   "basis": "reading"
  },
  {
   "from": "core.messages",
   "to": "x.aishared",
   "label": "replies through msg",
   "basis": "reading"
  },
  {
   "from": "core.sources",
   "to": "core.poller",
   "label": "defines jobs for",
   "basis": "imports"
  },
  {
   "from": "core.sources",
   "to": "core.messages",
   "label": "parses messages with",
   "basis": "imports"
  },
  {
   "from": "core.sources",
   "to": "core.safety",
   "label": "filters with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.poller",
   "to": "core.sources",
   "label": "runs",
   "basis": "imports"
  },
  {
   "from": "core.snapshot",
   "to": "core.poller",
   "label": "reads states from",
   "basis": "imports"
  },
  {
   "from": "core.snapshot",
   "to": "core.sources",
   "label": "merges",
   "basis": "imports"
  },
  {
   "from": "core.snapshot",
   "to": "core.messages",
   "label": "adds threads from",
   "basis": "imports"
  },
  {
   "from": "core.snapshot",
   "to": "core.safety",
   "label": "leak-scans with",
   "basis": "imports"
  },
  {
   "from": "core.messages",
   "to": "core.safety",
   "label": "allowlists with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.runtime",
   "to": "core.sources",
   "label": "supplies runtime to",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.runtime",
   "to": "core.poller",
   "label": "supplies runtime to",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.contracts",
   "to": "core.messages",
   "label": "projects",
   "basis": "imports"
  },
  {
   "from": "service.runtime",
   "to": "core.poller",
   "label": "runs its own",
   "basis": "imports"
  },
  {
   "from": "service.runtime",
   "to": "core.snapshot",
   "label": "builds snapshots with",
   "basis": "imports"
  },
  {
   "from": "service.runtime",
   "to": "service.api",
   "label": "starts",
   "basis": "imports"
  },
  {
   "from": "service.runtime",
   "to": "service.pairing",
   "label": "opens",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.runtime",
   "to": "service.auth",
   "label": "wires",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.runtime",
   "to": "service.registry",
   "label": "loads",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.runtime",
   "to": "service.audit",
   "label": "writes",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.api",
   "to": "core.contracts",
   "label": "serves projected",
   "basis": "imports"
  },
  {
   "from": "service.api",
   "to": "service.auth",
   "label": "authenticates with",
   "basis": "imports"
  },
  {
   "from": "service.api",
   "to": "service.audit",
   "label": "records to",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.api",
   "to": "service.pairing",
   "label": "redeems pairing codes with",
   "basis": "imports"
  },
  {
   "from": "service.pairing",
   "to": "service.registry",
   "label": "updates",
   "basis": "imports"
  },
  {
   "from": "service.pairing",
   "to": "service.auth",
   "label": "issues tokens with",
   "basis": "imports"
  },
  {
   "from": "service.pairing",
   "to": "service.audit",
   "label": "records to",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.auth",
   "to": "service.registry",
   "label": "checks generation in",
   "basis": "imports"
  },
  {
   "from": "service.auth",
   "to": "x.keychain",
   "label": "verifies tokens with",
   "basis": "reading"
  },
  {
   "from": "service.audit",
   "to": "service.registry",
   "label": "names devices from",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.tailscale",
   "to": "x.tailscale",
   "label": "plans Serve with",
   "basis": "reading"
  },
  {
   "from": "x.tailscale",
   "to": "service.api",
   "label": "forwards phone requests to",
   "basis": "reading"
  },
  {
   "from": "phone.transport",
   "to": "service.api",
   "label": "fetches snapshot and events from",
   "basis": "reading"
  },
  {
   "from": "phone.transport",
   "to": "phone.credentials",
   "label": "reads token from",
   "basis": "imports"
  },
  {
   "from": "phone.transport",
   "to": "core.contracts",
   "label": "validates against",
   "basis": "imports"
  },
  {
   "from": "phone.views",
   "to": "phone.transport",
   "label": "subscribes through",
   "basis": "imports"
  },
  {
   "from": "phone.views",
   "to": "phone.credentials",
   "label": "pairs with",
   "basis": "imports"
  },
  {
   "from": "phone.views",
   "to": "ui.viewmodel",
   "label": "reuses",
   "basis": "imports"
  },
  {
   "from": "phone.views",
   "to": "ui.messages",
   "label": "reuses markdown from",
   "basis": "imports"
  },
  {
   "from": "phone.fixtures",
   "to": "phone.views",
   "label": "renders on canned data",
   "basis": "imports"
  },
  {
   "from": "phone.fixtures",
   "to": "phone.transport",
   "label": "fakes",
   "basis": "imports"
  },
  {
   "from": "core.messages",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "core.poller",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "core.runtime",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "core.runtime",
   "to": "core.messages",
   "label": "runs msg for",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.runtime",
   "to": "core.safety",
   "label": "bounds reads with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.runtime",
   "to": "core.snapshot",
   "label": "supplies runtime to",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "core.safety",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "core.snapshot",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "core.sources",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "desktop.goto",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "desktop.goto",
   "to": "core.runtime",
   "label": "runs tmux through",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.messages",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "desktop.messages",
   "to": "core.runtime",
   "label": "runs msg through",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "desktop.messages",
   "to": "core.sources",
   "label": "finds senders with",
   "basis": "imports"
  },
  {
   "from": "desktop.summaries",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "desktop.summaries",
   "to": "core.runtime",
   "label": "runs ai-route through",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "phone.fixtures",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "phone.views",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "service.api",
   "to": "core.messages",
   "label": "projects threads with",
   "basis": "imports"
  },
  {
   "from": "service.api",
   "to": "core.safety",
   "label": "scans egress with",
   "basis": "imports"
  },
  {
   "from": "service.audit",
   "to": "core.safety",
   "label": "bounds fields with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.registry",
   "to": "core.safety",
   "label": "bounds fields with",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.runtime",
   "to": "core.messages",
   "label": "reads messages with",
   "basis": "imports"
  },
  {
   "from": "service.runtime",
   "to": "core.runtime",
   "label": "runs on",
   "basis": "imports",
   "minor": true
  },
  {
   "from": "service.runtime",
   "to": "core.sources",
   "label": "polls",
   "basis": "imports"
  },
  {
   "from": "ui.app",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui.board",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui.leads",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui.messages",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui.quota",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui.viewmodel",
   "to": "core.contracts",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "ui",
   "to": "desktop",
   "label": "reads snapshot over IPC",
   "basis": "reading"
  },
  {
   "from": "desktop",
   "to": "core",
   "label": "polls through",
   "basis": "imports"
  },
  {
   "from": "ui",
   "to": "core",
   "label": "uses types from",
   "basis": "imports"
  },
  {
   "from": "desktop",
   "to": "x.terminal",
   "label": "focuses",
   "basis": "reading"
  },
  {
   "from": "desktop",
   "to": "x.aishared",
   "label": "summarises with",
   "basis": "reading"
  },
  {
   "from": "core",
   "to": "x.aishared",
   "label": "polls",
   "basis": "reading"
  },
  {
   "from": "core",
   "to": "x.github",
   "label": "lists PRs from",
   "basis": "reading"
  },
  {
   "from": "core",
   "to": "x.terminal",
   "label": "lists panes from",
   "basis": "reading"
  },
  {
   "from": "service",
   "to": "core",
   "label": "runs its own",
   "basis": "imports"
  },
  {
   "from": "service",
   "to": "x.keychain",
   "label": "verifies tokens with",
   "basis": "reading"
  },
  {
   "from": "service",
   "to": "x.tailscale",
   "label": "plans Serve with",
   "basis": "reading"
  },
  {
   "from": "x.tailscale",
   "to": "service",
   "label": "forwards phone requests to",
   "basis": "reading"
  },
  {
   "from": "phone",
   "to": "service",
   "label": "fetches snapshot from",
   "basis": "reading"
  },
  {
   "from": "phone",
   "to": "ui",
   "label": "reuses formatting from",
   "basis": "imports"
  },
  {
   "from": "phone",
   "to": "core",
   "label": "uses types from",
   "basis": "imports"
  }
 ]
});
