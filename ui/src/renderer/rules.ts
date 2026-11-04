// The rule a statement's word choices build, mirrored from chad/approvals.py so the window can
// warn before the dispatcher refuses. The dispatcher re-checks everything.

import type { StatementView, WordMode } from '../shared/types';

export const WILDCARD = '*';

export function buildTerms(words: string[], modes: WordMode[]): string[] {
  const terms: string[] = [];
  words.forEach((word, index) => {
    const mode = modes[index] ?? 'keep';
    if (mode === 'drop') return;
    const term = mode === 'wild' ? WILDCARD : word;
    if (term === WILDCARD && terms[terms.length - 1] === WILDCARD) return;
    terms.push(term);
  });
  return terms;
}

const REDIRECT_OPERATOR = /^(?:\d+|&|\*)?(?:>>|>\||>|<)$/;
const NULL_TARGETS = new Set(['/dev/null', 'nul', '$null']);

/** Positions of each redirection to a file, operator and target (analysis.redirect_words). */
export function redirectWords(items: string[]): Set<number> {
  const found = new Set<number>();
  items.forEach((item, index) => {
    if (!REDIRECT_OPERATOR.test(item)) return;
    const target = items[index + 1] ?? '';
    if (NULL_TARGETS.has(target.replace(/^['"]+|['"]+$/g, '').toLowerCase())) return;
    found.add(index);
    if (target) found.add(index + 1);
  });
  return found;
}

/** A wildcard stands for one or more words, never for a redirect to a file. */
export function matches(terms: string[], items: string[]): boolean {
  const guarded = redirectWords(items);
  const from = (t: number, i: number): boolean => {
    if (t === terms.length) return i === items.length;
    if (terms[t] === WILDCARD) {
      for (let end = i + 1; end <= items.length && !guarded.has(end - 1); end++) {
        if (from(t + 1, end)) return true;
      }
      return false;
    }
    return i < items.length && items[i] === terms[t] && from(t + 1, i + 1);
  };
  return from(0, 0);
}

export interface Preview {
  text: string;
  valid: boolean;
}

export function preview(statement: StatementView, modes: WordMode[]): Preview {
  if (modes.every((mode) => mode === 'keep')) return { text: statement.normalized, valid: true };
  const terms = buildTerms(statement.words, modes);
  const text = terms.join(' ');
  if (terms.length === 0 || !matches(terms, statement.words)) {
    return {
      text: `"${text || '(nothing)'}" would not allow this statement itself`,
      valid: false,
    };
  }
  return { text, valid: true };
}
