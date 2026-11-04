// The approval view: one queued command at a time, a word editor per statement, the decision.

import type { Decision, PendingView, Selection, UiRequest, UiResponse, UiState, WordMode } from '../shared/types';
import { h, toast } from './dom';
import { preview } from './rules';

// Buttons stay disabled this long after a command appears, so a click or keystroke aimed at
// whatever was there before cannot answer it.
export const ARMING_MS = 900;

interface Editor {
  modes: WordMode[][];
  once: boolean[];
  denying: boolean;
  reason: string;
  shownAt: number;
}

type Act = (request: UiRequest) => Promise<UiResponse>;

export class ApprovalView {
  private items: PendingView[] = [];
  private currentId: string | null = null;
  private readonly editors = new Map<string, Editor>();
  private readonly header = h('div', { class: 'approval-header' });
  private readonly card = h('div', { class: 'approval-card', tabindex: '-1' });
  private readonly buttons = h('div', { class: 'decisions' });
  private armTimer: number | undefined;
  private busy = false;

  constructor(
    private readonly root: HTMLElement,
    private readonly act: Act,
  ) {
    root.append(this.header, this.card, this.buttons);
    window.setInterval(() => this.renderHeader(), 1000);
  }

  update(state: UiState): void {
    this.items = state.pending;
    for (const id of [...this.editors.keys()]) {
      if (!this.items.some((item) => item.id === id)) this.editors.delete(id);
    }
    const stillThere = this.items.some((item) => item.id === this.currentId);
    if (!stillThere) this.show(this.items[0]?.id ?? null);
    else this.renderHeader();
  }

  private get current(): PendingView | undefined {
    return this.items.find((item) => item.id === this.currentId);
  }

  private editor(item: PendingView): Editor {
    let editor = this.editors.get(item.id);
    if (!editor) {
      editor = {
        modes: item.statements.map((s) => s.words.map((): WordMode => 'keep')),
        once: item.statements.map(() => false),
        denying: false,
        reason: '',
        shownAt: 0,
      };
      this.editors.set(item.id, editor);
    }
    return editor;
  }

  private show(id: string | null): void {
    this.currentId = id;
    const item = this.current;
    if (item) {
      const editor = this.editor(item);
      if (!editor.shownAt) editor.shownAt = Date.now();
      window.clearTimeout(this.armTimer);
      const wait = editor.shownAt + ARMING_MS - Date.now();
      if (wait > 0) this.armTimer = window.setTimeout(() => this.renderButtons(), wait);
    }
    this.renderHeader();
    this.renderCard();
    this.renderButtons();
    this.card.focus({ preventScroll: true });
  }

  // Built once; renderHeader only updates it, so nothing under the pointer is replaced while
  // the user aims at it.
  private readonly previous = h('button', {
    class: 'nav',
    'aria-label': 'Previous command',
    onclick: () => this.step(-1),
  }, '‹');
  private readonly next = h('button', {
    class: 'nav',
    'aria-label': 'Next command',
    onclick: () => this.step(1),
  }, '›');
  private readonly position = h('span', { class: 'position' });
  private readonly countdown = h('span', {
    class: 'countdown',
    title: 'Answered "no decision in time" when this runs out',
  });
  private readonly emptyNote = h('p', { class: 'empty' }, 'No command is waiting for approval.');

  private step(by: number): void {
    const index = this.items.findIndex((item) => item.id === this.currentId);
    const target = this.items[index + by];
    if (target) this.show(target.id);
  }

  private renderHeader(): void {
    const item = this.current;
    if (!item) {
      if (this.header.firstChild !== this.emptyNote) this.header.replaceChildren(this.emptyNote);
      return;
    }
    if (this.header.firstChild !== this.previous) {
      this.header.replaceChildren(this.previous, this.position, this.next, this.countdown);
    }
    const index = this.items.indexOf(item);
    this.previous.disabled = index === 0;
    this.next.disabled = index === this.items.length - 1;
    this.position.textContent = `Command ${index + 1} of ${this.items.length}`;
    const seconds = Math.max(0, Math.round((item.deadline - Date.now()) / 1000));
    this.countdown.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  }

  private renderCard(): void {
    const item = this.current;
    if (!item) {
      this.card.replaceChildren();
      return;
    }
    const editor = this.editor(item);
    const adding = item.purpose === 'addSelective';
    const chain = item.statements.length > 1;
    const parts: (Node | null)[] = [
      adding
        ? h('p', { class: 'banner' }, 'Add to the Selective rules: choose which words are fixed and which may vary.')
        : null,
      h('pre', { class: 'command', 'data-testid': 'command' }, item.command),
      item.description ? h('p', { class: 'description' }, item.description) : null,
      ...item.statements.map((statement, index) => {
        const modes = editor.modes[index];
        const result = preview(statement, modes);
        let status: string;
        if (statement.allowedBy) status = `Already allowed (${statement.allowedBy})`;
        else if (statement.blocking.length) status = `Contains ${statement.blocking.join(', ')}: can only be allowed once`;
        else status = 'New';
        return h(
          'div',
          { class: 'statement', 'data-testid': 'statement' },
          chain ? h('div', { class: 'statement-text' }, statement.text) : null,
          h('div', { class: `status${statement.storable ? '' : ' muted'}` }, status),
          statement.storable
            ? h(
                'div',
                { class: 'tiles' },
                statement.words.map((word, w) => this.tile(item, index, w, word, modes[w])),
              )
            : null,
          statement.storable && !editor.once[index]
            ? h(
                'div',
                { class: `preview${result.valid ? '' : ' invalid'}`, 'data-testid': 'preview' },
                result.valid ? `Allows: ${result.text}` : result.text,
              )
            : null,
          statement.storable && chain && !adding
            ? h(
                'label',
                { class: 'once' },
                h('input', {
                  type: 'checkbox',
                  checked: editor.once[index],
                  onchange: (event: Event) => {
                    editor.once[index] = (event.target as HTMLInputElement).checked;
                    this.renderCard();
                    this.renderButtons();
                  },
                }),
                'Allow this statement only once',
              )
            : null,
        );
      }),
      h(
        'dl',
        { class: 'context' },
        h('dt', {}, 'Tool'), h('dd', {}, item.tool),
        h('dt', {}, 'Folder'), h('dd', {}, item.cwd || '-'),
        h('dt', {}, 'Session'), h('dd', {}, item.sessionId || '-'),
        h('dt', {}, 'Permission mode'), h('dd', {}, item.permissionMode || '-'),
      ),
    ];
    this.card.replaceChildren(...parts.filter((part): part is Node => part !== null));
  }

  private tile(item: PendingView, statement: number, index: number, word: string, mode: WordMode): HTMLElement {
    const editor = this.editor(item);
    const set = (next: WordMode) => {
      editor.modes[statement][index] = next;
      this.renderCard();
      this.renderButtons();
    };
    return h(
      'div',
      { class: `tile ${mode}`, 'data-testid': 'tile' },
      h('span', { class: 'word' }, mode === 'wild' ? '*' : word),
      h(
        'label',
        { title: 'The rule needs this word' },
        h('input', {
          type: 'checkbox',
          checked: mode !== 'drop',
          'aria-label': `Keep ${word}`,
          onchange: (event: Event) => set((event.target as HTMLInputElement).checked ? 'keep' : 'drop'),
        }),
        'Keep',
      ),
      h(
        'button',
        {
          class: `star${mode === 'wild' ? ' on' : ''}`,
          title: 'Anything may stand here',
          'aria-label': `Wildcard ${word}`,
          'aria-pressed': mode === 'wild' ? 'true' : 'false',
          onclick: () => set(mode === 'wild' ? 'keep' : 'wild'),
        },
        '*',
      ),
    );
  }

  private selections(item: PendingView): Selection[] {
    const editor = this.editor(item);
    return item.statements.map((_, index) => ({
      index,
      modes: editor.modes[index],
      once: editor.once[index],
    }));
  }

  private rulesValid(item: PendingView): boolean {
    const editor = this.editor(item);
    return item.statements.every(
      (statement, index) => !statement.storable || editor.once[index] || preview(statement, editor.modes[index]).valid,
    );
  }

  private renderButtons(): void {
    const item = this.current;
    if (!item) {
      this.buttons.replaceChildren();
      return;
    }
    const editor = this.editor(item);
    const armed = Date.now() - editor.shownAt >= ARMING_MS && !this.busy;
    const valid = this.rulesValid(item);
    const adding = item.purpose === 'addSelective';
    const blocked = item.statements.some((s) => s.blocking.length > 0);
    const button = (label: string, decision: Decision, extra: { disabled?: boolean; class?: string; title?: string } = {}) =>
      h(
        'button',
        {
          class: extra.class ?? 'secondary',
          disabled: !armed || extra.disabled,
          title: extra.title,
          tabindex: '-1',
          onclick: () => void this.decide(item, decision),
        },
        label,
      );

    if (editor.denying) {
      const reason = h('textarea', {
        class: 'reason',
        placeholder: 'Why not? The model reads this. (optional)',
        rows: 2,
        oninput: (event: Event) => (editor.reason = (event.target as HTMLTextAreaElement).value),
      });
      reason.value = editor.reason;
      this.buttons.replaceChildren(
        reason,
        h('div', { class: 'row' },
          button(adding ? 'Cancel the request' : 'Deny', 'deny', { class: 'danger' }),
          h('button', {
            class: 'secondary',
            tabindex: '-1',
            onclick: () => {
              editor.denying = false;
              this.renderButtons();
            },
          }, 'Back'),
        ),
      );
      reason.focus();
      return;
    }

    const deny = h('button', {
      class: 'danger',
      disabled: !armed,
      tabindex: '-1',
      onclick: () => {
        editor.denying = true;
        this.renderButtons();
      },
    }, adding ? 'Cancel' : 'Deny…');

    if (adding) {
      this.buttons.replaceChildren(
        h('div', { class: 'row' },
          button('Add selectively and run', 'allowSelective', {
            class: 'primary',
            disabled: !valid || blocked,
            title: blocked ? 'A statement contains a construct no rule can allow' : undefined,
          }),
          deny,
        ),
      );
      return;
    }
    const title = valid ? undefined : 'Fix the rule above: it would not allow its own statement';
    this.buttons.replaceChildren(
      h('div', { class: 'row' },
        button('Allow once', 'allowOnce', { class: 'primary' }),
        button('Allow forever', 'allowForever', { disabled: !valid, title }),
        button('Allow selectively', 'allowSelective', { disabled: !valid, title }),
        deny,
      ),
    );
  }

  private async decide(item: PendingView, decision: Decision): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.renderButtons();
    const editor = this.editor(item);
    const response = await this.act({
      action: 'decide',
      id: item.id,
      decision,
      reason: decision === 'deny' ? editor.reason : undefined,
      selections: this.selections(item),
    });
    this.busy = false;
    if (!response.ok) toast(response.error ?? 'CHAD refused that.');
    this.renderButtons();
  }
}
