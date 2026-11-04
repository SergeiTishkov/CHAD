import type { ChadBridge, UiState } from '../shared/types';
import { ApprovalView } from './approval';
import { $ } from './dom';
import { PolicyView } from './policy';

declare global {
  interface Window {
    chad: ChadBridge;
  }
}

type View = 'approval' | 'policy';

const act = window.chad.act;
const approval = new ApprovalView($('approval'), act);
const policy = new PolicyView($('policy'), act);
let view: View = 'policy';
let seenAttention = -1;

function show(next: View): void {
  view = next;
  $('approval').hidden = view !== 'approval';
  $('policy').hidden = view !== 'policy';
  $('view-approval').classList.toggle('active', view === 'approval');
  $('view-policy').classList.toggle('active', view === 'policy');
}

function apply(state: UiState | null): void {
  $('offline').hidden = state !== null;
  if (!state) return;
  approval.update(state);
  policy.update(state);
  const count = state.pending.length;
  $('pending-count').textContent = count ? String(count) : '';
  if (state.attentionVersion !== seenAttention) {
    seenAttention = state.attentionVersion;
    show(state.requestedView ?? (count ? 'approval' : 'policy'));
  } else if (view === 'approval' && count === 0) {
    show('policy');
  }
}

$('view-approval').addEventListener('click', () => show('approval'));
$('view-policy').addEventListener('click', () => show('policy'));
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') window.chad.hide();
});

show('policy');
window.chad.onState(apply);
void window.chad.getState().then(apply);
