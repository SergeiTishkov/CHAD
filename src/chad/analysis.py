"""Splitting a command line into statements and spotting what cannot be judged from text.

Allow rules match text. Some constructs run something the text does not show - a command
substitution, for one - so a statement carrying one is never auto-allowed, whatever rule
appears to match it. Those are "blocking constructs".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Dialect = Literal["bash", "powershell"]

COMMAND_SUBSTITUTION = "command substitution"
BACKTICK_SUBSTITUTION = "backtick command substitution"
PROCESS_SUBSTITUTION = "process substitution"
HERE_DOCUMENT = "here-document"
HERE_STRING = "here-string"
FILE_REDIRECTION = "file redirection"
EVAL = "eval/exec/source"
PS_SUBEXPRESSION = "$( ) subexpression"
PS_ARRAY_SUBEXPRESSION = "@( ) subexpression"
PS_BACKTICK = "backtick escape"
PS_CALL_OPERATOR = "& call operator"
PS_STOP_PARSING = "--% stop-parsing token"
PS_INVOKE_EXPRESSION = "Invoke-Expression"
PS_EXPRESSION = "( ) expression"

BASH_NULL_TARGETS = frozenset({"/dev/null", "nul"})
POWERSHELL_NULL_TARGETS = frozenset({"$null", "nul"})
NULL_TARGETS = BASH_NULL_TARGETS | POWERSHELL_NULL_TARGETS

# A redirect to a plain relative path in the working folder is part of the text a rule names: no
# variables, globs, home or drive, no `..`. PowerShell also takes `\` as a path separator.
LOCAL_TARGET = {"bash": re.compile(r"[\w.\-/]+"), "powershell": re.compile(r"[\w.\-/\\]+")}
# What `&` may call and still be judged by its text: a program or script named by a literal
# path. A single-quoted string is always literal; a double-quoted one when it expands nothing.
CALL_TARGET_BARE = re.compile(r"[\w.\-/\\:]+")
CALL_TARGET_SINGLE = re.compile(r"'(?:[^']|'')*'")
CALL_TARGET_DOUBLE = re.compile(r'"[^"$`]*"')
# A word that is a redirection operator, with its stream prefix (2>, &>, *>); not 2>&1.
REDIRECT_OPERATOR = re.compile(r"(?:\d+|&|\*)?(?:>>|>\||>|<)")
BASH_EVAL_WORDS = frozenset({"eval", "exec", "source", "."})

# $(cat <<'EOF' ... EOF) with a quoted delimiter expands nothing. Claude Code writes multi-line
# commit messages this way.
LITERAL_HEREDOC_START = re.compile(r"""\$\(\s*cat\s+<<(-?)\s*(['"])(\w+)\2[ \t]*\n""")
LITERAL_HEREDOC_END = re.compile(r"\s*\)")

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
INVOKE_EXPRESSION = re.compile(r"(?<![\w-])(iex|invoke-expression)(?![\w-])", re.IGNORECASE)


@dataclass(frozen=True)
class Statement:
    text: str
    normalized: str
    blocking: tuple[str, ...] = ()


@dataclass(frozen=True)
class Analysis:
    statements: tuple[Statement, ...]

    @property
    def is_empty(self) -> bool:
        return not self.statements

    @property
    def blocking(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for statement in self.statements:
            for construct in statement.blocking:
                seen.setdefault(construct)
        return tuple(seen)


def dialect_for_tool(tool_name: str | None) -> Dialect:
    return "powershell" if (tool_name or "").lower() == "powershell" else "bash"


def literal_heredoc_end(text: str, index: int) -> int | None:
    """End of $(cat <<'EOF' ... EOF) starting at index, or None if the text there is not one.

    The body ends at the first line that is exactly the delimiter (after leading tabs for <<-),
    as in bash, and the substitution must close right after it.
    """
    start = LITERAL_HEREDOC_START.match(text, index)
    if not start:
        return None
    strip_tabs, delimiter = start.group(1) == "-", start.group(3)
    position = start.end()
    while True:
        end = text.find("\n", position)
        if end < 0:
            return None
        line = text[position:end]
        if (line.lstrip("\t") if strip_tabs else line) == delimiter:
            break
        position = end + 1
    close = LITERAL_HEREDOC_END.match(text, end + 1)
    return close.end() if close else None


class _Scanner:
    def __init__(self, line: str, dialect: Dialect) -> None:
        self.line = line
        self.dialect = dialect
        self.bash = dialect == "bash"
        self.i = 0
        self.groups: list[str] = []  # closing character of each open group
        self.raw: list[str] = []
        self.norm: list[str] = []
        self.found: list[str] = []
        self.statements: list[Statement] = []

    # -- buffers -----------------------------------------------------------------------------

    def note(self, construct: str) -> None:
        if construct not in self.found:
            self.found.append(construct)

    def emit(self, text: str) -> None:
        self.raw.append(text)
        self.norm.append(text)

    def space(self, char: str) -> None:
        self.raw.append(char)
        if self.norm and self.norm[-1] != " ":
            self.norm.append(" ")

    def at_word_start(self) -> bool:
        if not self.raw:
            return True
        last = self.raw[-1][-1:]
        return last.isspace() or last in "({;"

    def at_command_start(self) -> bool:
        normalized = "".join(self.norm).rstrip()
        return not normalized or normalized[-1] in "({;|&"

    def open_group(self, opening: str, closing: str) -> None:
        self.emit(opening)
        self.groups.append(closing)
        self.i += len(opening)

    def flush(self) -> None:
        text = "".join(self.raw).strip()
        normalized = "".join(self.norm).strip()
        if normalized:
            for construct in self._word_constructs(text, normalized):
                self.note(construct)
            self.statements.append(Statement(text, normalized, tuple(self.found)))
        self.raw, self.norm, self.found = [], [], []

    def _word_constructs(self, text: str, normalized: str) -> list[str]:
        found: list[str] = []
        if self.bash:
            first = next((w for w in words(normalized, "bash") if not ASSIGNMENT.match(w)), "")
            if first in BASH_EVAL_WORDS:
                found.append(EVAL)
        else:
            if INVOKE_EXPRESSION.search(text):
                found.append(PS_INVOKE_EXPRESSION)
            if "--%" in text:
                found.append(PS_STOP_PARSING)
        return found

    # -- helpers -----------------------------------------------------------------------------

    def peek(self, offset: int = 0) -> str:
        index = self.i + offset
        return self.line[index] if index < len(self.line) else ""

    def redirect_target(self, start: int) -> str:
        """The target word after a redirection operator, as written."""
        index = start
        while index < len(self.line) and self.line[index] in " \t":
            index += 1
        end = index
        while (
            end < len(self.line) and not self.line[end].isspace() and self.line[end] not in ";|&<>)"
        ):
            end += 1
        return self.line[index:end]

    def redirection(self, operator_length: int) -> None:
        """Consume a redirection operator and judge it by where it writes."""
        operator = self.line[self.i : self.i + operator_length]
        nulls = BASH_NULL_TARGETS if self.bash else POWERSHELL_NULL_TARGETS
        target = self.redirect_target(self.i + operator_length)
        if target.strip("'\"").lower() not in nulls and not local_target(target, self.dialect):
            self.note(FILE_REDIRECTION)
        self.emit(operator)
        self.i += operator_length

    def literal_call_target(self) -> bool:
        """Whether the `&` at the cursor calls a literal path: `& "C:/x/tool.exe"`."""
        index = self.i + 1
        while index < len(self.line) and self.line[index] in " \t":
            index += 1
        rest = self.line[index:]
        for target in (CALL_TARGET_SINGLE, CALL_TARGET_DOUBLE, CALL_TARGET_BARE):
            found = target.match(rest)
            if found:
                after = rest[found.end() : found.end() + 1]
                return not after or after.isspace() or after in ";|"
        return False

    def fd_duplication(self) -> int:
        """Length of an fd duplication such as >&2, >&-, <&0 at the cursor, else 0."""
        if (
            self.peek() in "<>"
            and self.peek(1) == "&"
            and (self.peek(2).isdigit() or self.peek(2) == "-")
        ):
            return 3
        return 0

    def literal_heredoc(self) -> bool:
        end = literal_heredoc_end(self.line, self.i) if self.bash else None
        if end is None:
            return False
        self.emit(self.line[self.i : end])
        self.i = end
        return True

    # -- quoted text -------------------------------------------------------------------------

    def single_quoted(self) -> None:
        self.emit("'")
        self.i += 1
        while self.i < len(self.line):
            char = self.line[self.i]
            self.emit(char)
            self.i += 1
            if char == "'":
                if not self.bash and self.peek() == "'":
                    self.emit("'")
                    self.i += 1
                    continue
                return

    def ansi_quoted(self) -> None:
        self.emit("$'")
        self.i += 2
        while self.i < len(self.line):
            char = self.line[self.i]
            if char == "\\" and self.i + 1 < len(self.line):
                self.emit(self.line[self.i : self.i + 2])
                self.i += 2
                continue
            self.emit(char)
            self.i += 1
            if char == "'":
                return

    def double_quoted(self) -> None:
        self.emit('"')
        self.i += 1
        while self.i < len(self.line):
            char = self.line[self.i]
            if self.bash and char == "\\" and self.i + 1 < len(self.line):
                self.emit(self.line[self.i : self.i + 2])
                self.i += 2
                continue
            if char == "`":
                self.note(BACKTICK_SUBSTITUTION if self.bash else PS_BACKTICK)
                if not self.bash and self.i + 1 < len(self.line):
                    self.emit(self.line[self.i : self.i + 2])
                    self.i += 2
                    continue
            if char == "$" and self.peek(1) == "(":
                if self.literal_heredoc():
                    continue
                self.note(COMMAND_SUBSTITUTION if self.bash else PS_SUBEXPRESSION)
            self.emit(char)
            self.i += 1
            if char == '"':
                if not self.bash and self.peek() == '"':
                    self.emit('"')
                    self.i += 1
                    continue
                return

    # -- main loop ---------------------------------------------------------------------------

    def run(self) -> tuple[Statement, ...]:
        line = self.line
        while self.i < len(line):
            char = line[self.i]
            nxt = self.peek(1)

            if char == "\r":
                self.i += 1
                continue
            if char == "\n":
                if not self.groups:
                    self.flush()
                else:
                    self.space(char)
                self.i += 1
                continue
            if char.isspace():
                self.space(char)
                self.i += 1
                continue
            if char == "#" and self.at_word_start():
                end = line.find("\n", self.i)
                end = len(line) if end < 0 else end
                self.raw.append(line[self.i : end])
                self.i = end
                continue
            if char == "'":
                self.single_quoted()
                continue
            if char == '"':
                self.double_quoted()
                continue
            if self.bash and char == "$" and nxt == "'":
                self.ansi_quoted()
                continue
            if self.bash and char == "\\" and nxt:
                self.emit(char + nxt)
                self.i += 2
                continue
            if char == "`":
                if self.bash:
                    self.note(BACKTICK_SUBSTITUTION)
                    self.emit(char)
                    self.i += 1
                else:
                    self.note(PS_BACKTICK)
                    self.emit(line[self.i : self.i + 2])
                    self.i += 2
                continue

            # Statement separators, only at the top level of the line.
            if not self.groups:
                if char == ";":
                    self.flush()
                    self.i += 1
                    continue
                if (char == "&" and nxt == "&") or (char == "|" and nxt == "|"):
                    self.flush()
                    self.i += 2
                    continue
                if self.bash and char == "|" and nxt == "&":
                    self.flush()
                    self.i += 2
                    continue
                if char == "|":
                    self.flush()
                    self.i += 1
                    continue

            # Grouping and substitutions.
            if char == "$" and nxt == "(":
                if self.literal_heredoc():
                    continue
                self.note(COMMAND_SUBSTITUTION if self.bash else PS_SUBEXPRESSION)
                self.open_group("$(", ")")
                continue
            if self.bash and char == "$" and nxt == "{":
                self.open_group("${", "}")
                continue
            if not self.bash and char == "@" and nxt == "(":
                self.note(PS_ARRAY_SUBEXPRESSION)
                self.open_group("@(", ")")
                continue
            if self.bash and char in "<>" and nxt == "(":
                self.note(PROCESS_SUBSTITUTION)
                self.open_group(char + "(", ")")
                continue
            if char == "(":
                if not self.bash:
                    self.note(PS_EXPRESSION)
                self.open_group("(", ")")
                continue
            # In bash { groups commands only as a word of its own where a command starts;
            # elsewhere it is an ordinary character, as in {a,b} or find -exec {}.
            if char == "{" and (not self.bash or (self.at_command_start() and nxt.isspace())):
                self.open_group("{", "}")
                continue
            if self.groups and char == self.groups[-1]:
                self.groups.pop()
                self.emit(char)
                self.i += 1
                continue

            # Redirection.
            length = self.fd_duplication()
            if length:
                self.emit(line[self.i : self.i + length])
                self.i += length
                continue
            if char == "&":
                if self.bash and nxt == ">":
                    self.redirection(3 if self.peek(2) == ">" else 2)
                elif self.bash:
                    # A single & sends the job to the background and ends the statement.
                    if not self.groups:
                        self.flush()
                    else:
                        self.emit(char)
                    self.i += 1
                else:
                    if not self.literal_call_target():
                        self.note(PS_CALL_OPERATOR)
                    self.emit(char)
                    self.i += 1
                continue
            if char == "<" and self.bash and line.startswith("<<<", self.i):
                self.note(HERE_STRING)
                self.emit("<<<")
                self.i += 3
                continue
            if char == "<" and self.bash and nxt == "<":
                self.note(HERE_DOCUMENT)
                self.emit("<<")
                self.i += 2
                continue
            if char == ">":
                self.redirection(2 if nxt in ">|" else 1)
                continue
            if char == "<":
                self.redirection(1)
                continue

            self.emit(char)
            self.i += 1

        self.flush()
        return tuple(self.statements)


def local_target(target: str, dialect: Dialect = "bash") -> bool:
    """A redirect target that names one file in the working folder: `out.log`, `logs/run.txt`."""
    if not LOCAL_TARGET[dialect].fullmatch(target) or target.startswith(("/", "\\")):
        return False
    return ".." not in re.split(r"[/\\]", target)


def redirect_words(items: Sequence[str]) -> frozenset[int]:
    """Positions of each redirection to a file, operator and target, in a statement's words.

    A wildcard does not stand for them, so a rule covers a redirect only by naming it. A redirect
    to the null device writes nowhere and is left out.
    """
    found: set[int] = set()
    for index, item in enumerate(items):
        if REDIRECT_OPERATOR.fullmatch(item):
            target = items[index + 1] if index + 1 < len(items) else ""
            if target.strip("'\"").lower() not in NULL_TARGETS:
                found.update({index, index + 1} if target else {index})
    return frozenset(found)


def analyze(command: str, dialect: Dialect = "bash") -> Analysis:
    if not command or not command.strip():
        return Analysis(())
    return Analysis(_Scanner(command, dialect).run())


def _redirect_operator(statement: str, i: int, dialect: Dialect) -> str:
    """The redirection operator at i (`>`, `>>`, `>|`, `<`), or "" for none or an fd duplication."""
    if statement[i] not in "<>" or re.match(r"[<>]&[\d-]", statement[i : i + 3]):
        return ""
    if dialect == "bash" and statement[i + 1 : i + 2] == "(":
        return ""  # process substitution: blocking, left as it is
    for operator in ("<<<", "<<", ">>", ">|", ">", "<"):
        if statement.startswith(operator, i):
            return operator
    return ""


def words(statement: str, dialect: Dialect = "bash") -> list[str]:
    """Split on whitespace outside quotes, keeping the quotes: "hello world" is one word.

    A redirection operator is a word of its own, with its stream prefix: `make 2>err.txt` is
    `make`, `2>`, `err.txt`. An fd duplication (`2>&1`) stays part of its word.
    """
    result: list[str] = []
    current: list[str] = []
    quote = ""
    i = 0
    while i < len(statement):
        char = statement[i]
        if quote:
            current.append(char)
            if dialect == "bash" and quote == '"' and char == "\\" and i + 1 < len(statement):
                current.append(statement[i + 1])
                i += 2
                continue
            if char == quote:
                quote = ""
            i += 1
            continue
        if dialect == "bash" and char == "$" and statement.startswith("$(", i):
            end = literal_heredoc_end(statement, i)
            if end is not None:
                current.append(statement[i:end])
                i = end
                continue
        if char in "'\"":
            quote = char
            current.append(char)
        elif dialect == "bash" and char == "\\" and i + 1 < len(statement):
            current.append(statement[i : i + 2])
            i += 2
            continue
        elif char.isspace():
            if current:
                result.append("".join(current))
                current = []
        elif operator := _redirect_operator(statement, i, dialect):
            prefix = "".join(current)
            # Rule text is read as bash, so `*>` (PowerShell's all streams) is an operator in both.
            stream = prefix.isdigit() or prefix in ("&", "*")
            if prefix and not stream:
                result.append(prefix)
            result.append((prefix if stream else "") + operator)
            current = []
            i += len(operator)
            continue
        else:
            current.append(char)
        i += 1
    if current:
        result.append("".join(current))
    return result
