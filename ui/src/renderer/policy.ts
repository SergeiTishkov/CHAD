// The policy view: the mode, the deny switch, and both rule lists.

import { MODE_LABELS, type UiRequest, type UiResponse, type UiState } from '../shared/types';
import { h, toast } from './dom';
import { WILDCARD } from './rules';

type Act = (request: UiRequest) => Promise<UiResponse>;
type Tab = 'allow' | 'deny';

export class PolicyView {
  private state: UiState | null = null;
  private tab: Tab = 'allow';
  private readonly modes = h('div', { class: 'modes', role: 'radiogroup', 'aria-label': 'Mode' });
  private readonly denySwitch = h('input', { type: 'checkbox', id: 'deny-switch' });
  private readonly tabs = h('div', { class: 'tabs', role: 'tablist' });
  private readonly search = h('input', { type: 'search', placeholder: 'Search', class: 'search' });
  private readonly addInput = h('input', { type: 'text', class: 'add-input' });
  private readonly addSelective = h('input', { type: 'checkbox' });
  private readonly addSelectiveLabel = h('label', { class: 'inline' }, this.addSelective, 'Selective');
  private readonly error = h('div', { class: 'list-error', role: 'alert' });
  private readonly table = h('table', { class: 'rules' });
  private readonly summary = h('p', { class: 'summary' });
  private dragKey: string | null = null;
  /** The allow rule being edited and its words as they stand in the editor. */
  private editing: { key: string; words: string[] } | null = null;

  constructor(
    root: HTMLElement,
    private readonly act: Act,
  ) {
    this.denySwitch.addEventListener('change', () =>
      void this.run({ action: 'setDeny', value: this.denySwitch.checked }),
    );
    this.search.addEventListener('input', () => this.renderTable());
    const add = h(
      'form',
      {
        class: 'add',
        onsubmit: (event: Event) => {
          event.preventDefault();
          void this.add();
        },
      },
      this.addInput,
      this.addSelectiveLabel,
      h('button', { type: 'submit', class: 'secondary' }, 'Add'),
    );
    root.append(
      h('h2', {}, 'Mode'),
      this.modes,
      h(
        'label',
        { class: 'deny-switch' },
        this.denySwitch,
        h('span', {}, h('strong', {}, 'Deny list armed'), ' - refuse the commands on the Denied tab in every mode except Off'),
      ),
      h('div', { class: 'list-bar' }, this.tabs, this.search),
      this.error,
      this.table,
      add,
      this.summary,
    );
  }

  update(state: UiState): void {
    this.state = state;
    this.renderModes();
    this.denySwitch.checked = state.deny;
    this.renderTabs();
    // An open editor keeps its row as it is, so typing is not interrupted; the table catches up
    // when it closes. A rule that went away closes it.
    if (this.editing && this.tab === 'allow') {
      if (state.allowList.entries.some((e) => e.key === this.editing!.key)) return;
      this.editing = null;
    }
    this.renderTable();
  }

  private async run(request: UiRequest): Promise<boolean> {
    const response = await this.act(request);
    if (!response.ok) toast(response.error ?? 'CHAD refused that.');
    return response.ok;
  }

  private renderModes(): void {
    const state = this.state!;
    this.modes.replaceChildren(
      ...state.modes.map((mode) =>
        h(
          'label',
          { class: `mode${mode.id === state.mode ? ' selected' : ''}`, 'data-mode': mode.id },
          h('input', {
            type: 'radio',
            name: 'mode',
            value: mode.id,
            checked: mode.id === state.mode,
            onchange: () => void this.run({ action: 'setMode', mode: mode.id }),
          }),
          h('span', { class: 'mode-name' }, MODE_LABELS[mode.id]),
          h('span', { class: 'mode-description' }, mode.description),
        ),
      ),
    );
  }

  private renderTabs(): void {
    const state = this.state!;
    const tab = (id: Tab, label: string, count: number) =>
      h(
        'button',
        {
          role: 'tab',
          class: this.tab === id ? 'active' : '',
          'aria-selected': this.tab === id ? 'true' : 'false',
          onclick: () => {
            this.tab = id;
            this.renderTabs();
            this.renderTable();
          },
        },
        `${label} (${count})`,
      );
    this.tabs.replaceChildren(
      tab('allow', 'Allowed', state.allowList.entries.length),
      tab('deny', 'Denied', state.denyList.rules.length),
    );
    this.addInput.placeholder =
      this.tab === 'allow' ? 'Allow a command or pattern, e.g. git log *' : 'Deny words, e.g. npm publish';
    this.addSelectiveLabel.hidden = this.tab !== 'allow';
  }

  private matchesSearch(text: string): boolean {
    const query = this.search.value.trim().toLowerCase();
    return !query || text.toLowerCase().includes(query);
  }

  private dropTarget(cell: HTMLElement, move: 'moveAllow' | 'moveDeny', index: number): HTMLElement {
    cell.addEventListener('dragover', (event) => event.preventDefault());
    cell.addEventListener('drop', (event) => {
      event.preventDefault();
      const key = this.dragKey;
      this.dragKey = null;
      if (key) void this.run({ action: move, key, index });
    });
    return cell;
  }

  private renderTable(): void {
    const state = this.state;
    if (!state) return;
    const list = this.tab === 'allow' ? state.allowList : state.denyList;
    this.error.textContent = list.error ?? '';
    this.error.hidden = !list.error;

    if (this.tab === 'allow') {
      const rows = state.allowList.entries
        .map((entry, index) => ({ entry, index }))
        .filter(({ entry }) => this.matchesSearch(entry.value));
      const boundary = state.allowList.entries.filter((e) => e.selective).length;
      this.table.replaceChildren(
        h('thead', {}, h('tr', {}, h('th', {}, 'Kind'), h('th', {}, 'Rule'), h('th'), h('th', {}, 'Selective'), h('th'), h('th'))),
        h(
          'tbody',
          {},
          rows.map(({ entry, index }) =>
            h(
              'tr',
              { class: index === boundary - 1 ? 'boundary' : '', 'data-key': entry.key },
              h('td', { class: 'kind' }, entry.kind),
              h(
                'td',
                { class: 'rule' },
                this.editing?.key === entry.key ? this.ruleEditor(entry.value) : h('code', {}, entry.value),
              ),
              h(
                'td',
                {},
                entry.kind !== 'regex' && !this.editing
                  ? h('button', {
                      class: 'link',
                      'aria-label': `Edit ${entry.value}`,
                      onclick: () => {
                        this.editing = { key: entry.key, words: [...entry.words] };
                        this.renderTable();
                      },
                    }, 'Edit')
                  : null,
              ),
              h('td', {}, h('input', {
                type: 'checkbox',
                checked: entry.selective,
                'aria-label': `Selective: ${entry.value}`,
                onchange: (event: Event) =>
                  void this.run({ action: 'setSelective', key: entry.key, value: (event.target as HTMLInputElement).checked }),
              })),
              h('td', {}, h('button', {
                class: 'link danger',
                'aria-label': `Delete ${entry.value}`,
                onclick: () => {
                  if (entry.kind === 'regex' && !window.confirm(`${entry.value} is a regex written in the file by hand. Delete it?`)) return;
                  void this.run({ action: 'deleteAllow', key: entry.key });
                },
              }, 'Delete')),
              this.dropTarget(this.gripCell(entry.key), 'moveAllow', index),
            ),
          ),
        ),
      );
      this.summary.textContent = `${state.allowList.entries.length} rules, ${boundary} Selective · ${state.allowList.path}`;
    } else {
      const rows = state.denyList.rules
        .map((rule, index) => ({ rule, index }))
        .filter(({ rule }) => this.matchesSearch(rule.words));
      this.table.replaceChildren(
        h('thead', {}, h('tr', {}, h('th', {}, 'On'), h('th', {}, 'Words'), h('th'), h('th'))),
        h(
          'tbody',
          {},
          rows.map(({ rule, index }) =>
            h(
              'tr',
              { 'data-key': rule.key },
              h('td', {}, h('input', {
                type: 'checkbox',
                checked: rule.enabled,
                'aria-label': `Enabled: ${rule.words}`,
                onchange: (event: Event) =>
                  void this.run({ action: 'setDenyRule', key: rule.key, value: (event.target as HTMLInputElement).checked }),
              })),
              h('td', { class: 'rule' }, h('code', {}, rule.words)),
              h('td', {}, h('button', {
                class: 'link danger',
                'aria-label': `Delete ${rule.words}`,
                onclick: () => {
                  if (!window.confirm(`Delete the deny rule "${rule.words}"?`)) return;
                  void this.run({ action: 'deleteDeny', key: rule.key });
                },
              }, 'Delete')),
              this.dropTarget(this.gripCell(rule.key), 'moveDeny', index),
            ),
          ),
        ),
      );
      const enabled = state.denyList.rules.filter((r) => r.enabled).length;
      this.summary.textContent = `${state.denyList.rules.length} rules, ${enabled} on${state.deny ? '' : ' (the list is not armed)'} · ${state.denyList.path}`;
    }
  }

  /** Words as tiles: retype one, make it `*`, move it, remove it, or add one. */
  private ruleEditor(original: string): HTMLElement {
    const editing = this.editing!;
    const result = h('code', { 'data-testid': 'edit-preview' });
    const showResult = () => {
      const terms: string[] = [];
      for (const word of editing.words.map((w) => w.trim()).filter(Boolean)) {
        if (word === WILDCARD && terms[terms.length - 1] === WILDCARD) continue;
        terms.push(word);
      }
      result.textContent = terms.join(' ') || '(nothing)';
    };
    const redraw = () => this.renderTable();
    const change = (update: (words: string[]) => void) => () => {
      update(editing.words);
      redraw();
    };
    const tiles = editing.words.map((word, index) => {
      const n = index + 1;
      const last = index === editing.words.length - 1;
      return h(
        'div',
        { class: `tile${word === WILDCARD ? ' wild' : ''}`, 'data-testid': 'edit-tile' },
        h('input', {
          type: 'text',
          class: 'word-input',
          value: word,
          'aria-label': `Word ${n}`,
          oninput: (event: Event) => {
            editing.words[index] = (event.target as HTMLInputElement).value;
            showResult();
          },
        }),
        h(
          'div',
          { class: 'tile-actions' },
          h('button', { type: 'button', 'aria-label': `Move word ${n} left`, disabled: index === 0,
            onclick: change((w) => w.splice(index - 1, 2, w[index], w[index - 1])) }, '←'),
          h('button', { type: 'button', class: `star${word === WILDCARD ? ' on' : ''}`, 'aria-label': `Wildcard word ${n}`,
            title: 'Anything may stand here', onclick: change((w) => (w[index] = WILDCARD)) }, '*'),
          h('button', { type: 'button', 'aria-label': `Move word ${n} right`, disabled: last,
            onclick: change((w) => w.splice(index, 2, w[index + 1], w[index])) }, '→'),
          h('button', { type: 'button', class: 'danger', 'aria-label': `Remove word ${n}`,
            onclick: change((w) => w.splice(index, 1)) }, '✕'),
        ),
      );
    });
    showResult();
    return h(
      'form',
      {
        class: 'rule-editor',
        onsubmit: (event: Event) => {
          event.preventDefault();
          void this.saveEdit();
        },
      },
      h('div', { class: 'tiles' }, tiles, h('button', { type: 'button', class: 'secondary', onclick: change((w) => w.push('')) }, '+ Word')),
      h('div', { class: 'edit-result' }, 'Rule: ', result),
      h(
        'div',
        { class: 'row' },
        h('button', { type: 'submit' }, 'Save'),
        h('button', { type: 'button', class: 'secondary', 'aria-label': `Cancel editing ${original}`,
          onclick: () => { this.editing = null; redraw(); } }, 'Cancel'),
      ),
    );
  }

  private async saveEdit(): Promise<void> {
    const editing = this.editing;
    if (!editing) return;
    const value = editing.words.map((w) => w.trim()).filter(Boolean).join(' ');
    if (await this.run({ action: 'editAllow', key: editing.key, value })) {
      this.editing = null;
      if (this.state) this.renderTable();
    }
  }

  private gripCell(key: string): HTMLElement {
    return h(
      'td',
      { class: 'grip-cell' },
      h('span', {
        class: 'grip',
        draggable: 'true',
        title: 'Drag to reorder',
        ondragstart: (event: DragEvent) => {
          this.dragKey = key;
          event.dataTransfer?.setData('text/plain', key);
        },
      }, '⠿'),
    );
  }

  private async add(): Promise<void> {
    const value = this.addInput.value.trim();
    if (!value) return;
    const ok =
      this.tab === 'allow'
        ? await this.run({ action: 'addAllow', value, selective: this.addSelective.checked })
        : await this.run({ action: 'addDeny', value });
    if (ok) this.addInput.value = '';
  }
}
