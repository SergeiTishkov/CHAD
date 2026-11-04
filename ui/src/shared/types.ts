// The dispatcher's UiState (docs/SPEC.md §9) as the window receives it.

export type ModeId = 'allowAll' | 'chad' | 'selective' | 'off';
export type Purpose = 'approve' | 'addSelective';
export type WordMode = 'keep' | 'wild' | 'drop';
export type Decision = 'allowOnce' | 'allowForever' | 'allowSelective' | 'deny';

export interface StatementView {
  text: string;
  normalized: string;
  words: string[];
  blocking: string[];
  allowedBy: string | null;
  storable: boolean;
}

export interface PendingView {
  id: string;
  command: string;
  tool: string;
  description: string;
  cwd: string;
  sessionId: string;
  permissionMode: string;
  purpose: Purpose;
  deadline: number;
  statements: StatementView[];
}

export interface AllowEntry {
  key: string;
  kind: 'exact' | 'pattern' | 'regex';
  value: string;
  selective: boolean;
  /** The rule's words for the editor; empty for a regex rule. */
  words: string[];
}

export interface DenyRule {
  key: string;
  words: string;
  enabled: boolean;
}

export interface UiState {
  mode: ModeId;
  modes: { id: ModeId; description: string }[];
  deny: boolean;
  pending: PendingView[];
  attentionVersion: number;
  requestedView: 'approval' | 'policy' | null;
  allowList: { path: string; error: string | null; entries: AllowEntry[] };
  denyList: { path: string; error: string | null; rules: DenyRule[] };
  dataRoot: string;
  budgetSeconds: number;
  pid: number;
}

export interface Selection {
  index: number;
  modes: WordMode[];
  once: boolean;
}

export interface UiRequest {
  action: string;
  [field: string]: unknown;
}

export interface UiResponse {
  ok: boolean;
  error?: string;
  state?: UiState;
}

export interface ChadBridge {
  onState(listener: (state: UiState | null) => void): void;
  getState(): Promise<UiState | null>;
  act(request: UiRequest): Promise<UiResponse>;
  hide(): void;
}

export const MODE_LABELS: Record<ModeId, string> = {
  chad: 'CHAD',
  allowAll: 'Allow all',
  selective: 'Selective Allowlist',
  off: 'Off - Claude Code decides',
};
