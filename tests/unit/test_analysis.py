from __future__ import annotations

import pytest

from chad import analysis as a
from chad.analysis import analyze, words


def texts(command: str, dialect: a.Dialect = "bash") -> list[str]:
    return [s.normalized for s in analyze(command, dialect).statements]


def blocking(command: str, dialect: a.Dialect = "bash") -> tuple[str, ...]:
    return analyze(command, dialect).blocking


# -- splitting ---------------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", ["bash", "powershell"])
def test_separators(dialect: a.Dialect) -> None:
    assert texts("a; b && c || d | e\nf", dialect) == ["a", "b", "c", "d", "e", "f"]


@pytest.mark.parametrize("dialect", ["bash", "powershell"])
def test_separators_inside_quotes_do_not_split(dialect: a.Dialect) -> None:
    assert texts("echo \"a; b && c\" 'd | e'", dialect) == ["echo \"a; b && c\" 'd | e'"]


@pytest.mark.parametrize("dialect", ["bash", "powershell"])
def test_whitespace_collapses_outside_quotes_only(dialect: a.Dialect) -> None:
    assert texts('git   commit  -m "two  spaces"', dialect) == ['git commit -m "two  spaces"']


def test_empty_and_comment_only_lines_have_no_statements() -> None:
    assert analyze("").is_empty
    assert analyze("   \n ").is_empty
    assert analyze("#chad:allow-deny-list").is_empty
    assert analyze("#chad:allow-deny-list", "powershell").is_empty


@pytest.mark.parametrize("dialect", ["bash", "powershell"])
def test_comments_are_removed_from_normalized_but_not_from_text(dialect: a.Dialect) -> None:
    statement = analyze("git status # just looking", dialect).statements[0]
    assert statement.normalized == "git status"
    assert statement.text == "git status # just looking"


def test_hash_inside_a_word_is_not_a_comment() -> None:
    assert texts("echo a#b") == ["echo a#b"]


def test_bash_single_ampersand_backgrounds_and_splits() -> None:
    assert texts("sleep 5 & echo done") == ["sleep 5", "echo done"]
    assert blocking("sleep 5 & echo done") == ()


def test_bash_pipe_ampersand_splits() -> None:
    assert texts("make |& tee") == ["make", "tee"]


def test_grouping_keeps_separators_inside() -> None:
    assert texts("(cd x; make) && echo ok") == ["(cd x; make)", "echo ok"]
    assert texts("ls | ForEach-Object { $_; $_ }", "powershell") == [
        "ls",
        "ForEach-Object { $_; $_ }",
    ]


def test_bash_brace_group_keeps_separators_inside() -> None:
    assert texts("{ a; b; } && c") == ["{ a; b; }", "c"]
    assert texts("x && { a; b; }") == ["x", "{ a; b; }"]
    assert texts("echo ${x//;/-}; ls") == ["echo ${x//;/-}", "ls"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git status {; rm -rf x", ["git status {", "rm -rf x"]),
        ("echo {a,b}; rm x", ["echo {a,b}", "rm x"]),
        ("echo }; rm x", ["echo }", "rm x"]),
        ("{a; rm x", ["{a", "rm x"]),
        ("find . -exec ls {} +; rm x", ["find . -exec ls {} +", "rm x"]),
    ],
)
def test_bash_brace_that_is_not_a_group_is_an_ordinary_character(
    command: str, expected: list[str]
) -> None:
    assert texts(command) == expected


def test_closing_character_must_match_the_open_group() -> None:
    assert texts("echo $(echo {); rm x") == ["echo $(echo {)", "rm x"]
    assert texts("echo $(echo }); rm x") == ["echo $(echo })", "rm x"]
    assert texts("echo ); rm x") == ["echo )", "rm x"]


def test_substitution_is_one_statement() -> None:
    statements = analyze("echo $(a; b) && c").statements
    assert [s.normalized for s in statements] == ["echo $(a; b)", "c"]
    assert statements[0].blocking == (a.COMMAND_SUBSTITUTION,)
    assert statements[1].blocking == ()


# -- bash blocking constructs ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "construct"),
    [
        ("echo $(whoami)", a.COMMAND_SUBSTITUTION),
        ('echo "$(whoami)"', a.COMMAND_SUBSTITUTION),
        ("echo `whoami`", a.BACKTICK_SUBSTITUTION),
        ('echo "`whoami`"', a.BACKTICK_SUBSTITUTION),
        ("diff <(ls a) <(ls b)", a.PROCESS_SUBSTITUTION),
        ("echo hi > ~/.bashrc", a.FILE_REDIRECTION),
        ("echo hi >> /etc/hosts", a.FILE_REDIRECTION),
        ("sort < ../in.txt", a.FILE_REDIRECTION),
        ("make &> logs/../../build.log", a.FILE_REDIRECTION),
        ("echo x >| $HOME/f", a.FILE_REDIRECTION),
        ('echo x > "$f"', a.FILE_REDIRECTION),
        ("echo x > *.log", a.FILE_REDIRECTION),
        ("echo x > out\\log", a.FILE_REDIRECTION),
        ("echo x > 'a b.log'", a.FILE_REDIRECTION),
        ("cat <<END\nhi\nEND", a.HERE_DOCUMENT),
        ("cat <<< hi", a.HERE_STRING),
        ("eval ls", a.EVAL),
        ("source env.sh", a.EVAL),
        (". env.sh", a.EVAL),
        ("FOO=1 exec ls", a.EVAL),
    ],
)
def test_bash_blocking(command: str, construct: str) -> None:
    assert construct in blocking(command)


@pytest.mark.parametrize(
    "command",
    [
        "make 2>&1",
        "make >&2",
        "exec_thing 3<&0",
        "ls 2>/dev/null",
        "ls > /dev/null 2>&1",
        "ls &>/dev/null",
        "echo '$(not run)' 'x > y'",
        "echo \\$HOME \\`x\\`",
        "echo $HOME ${PATH}",
        "find . -name x",
        "git log --format='%h > %s'",
        "echo $'a\\'b'",
        "echo hi > out.txt",
        "echo hi >> logs/out.txt",
        "sort < in.txt",
        "make &> build.log",
        "make 2>err.txt >out.txt",
        "echo x >| ./f",
        "dotnet test>red-run.log",
    ],
)
def test_bash_not_blocking(command: str) -> None:
    assert blocking(command) == ()


def test_claude_code_commit_idiom_is_literal() -> None:
    command = (
        "git add -A && git commit -m \"$(cat <<'MSG'\n"
        "Fix the parser; handle && and $(x) literally\n\n"
        "Co-Authored-By: Someone\n"
        "MSG\n"
        ')"'
    )
    statements = analyze(command).statements
    assert [s.normalized.split()[:2] for s in statements] == [["git", "add"], ["git", "commit"]]
    assert analyze(command).blocking == ()
    assert words(statements[1].normalized)[:3] == ["git", "commit", "-m"]
    assert len(words(statements[1].normalized)) == 4


def test_commit_idiom_outside_double_quotes_is_literal_too() -> None:
    command = "git commit -m $(cat <<'MSG'\nline one; two\nMSG\n)"
    assert texts(command) == [command]
    assert blocking(command) == ()


def test_unquoted_delimiter_heredoc_substitution_is_still_blocking() -> None:
    assert a.COMMAND_SUBSTITUTION in blocking('git commit -m "$(cat <<MSG\nx $(y)\nMSG\n)"')


@pytest.mark.parametrize(
    "command",
    [
        # The body ends at the first MSG line; what follows runs inside the substitution.
        "git commit -m \"$(cat <<'MSG'\nx\nMSG\nrm -rf ~\nMSG\n)\"",
        # Without <<-, an indented line is not the delimiter.
        "git commit -m \"$(cat <<'MSG'\nx\n  MSG\n)\"",
        "git commit -m \"$(cat <<'MSG'\nx\n\tMSG\n)\"",
        # Nor is a line with trailing blanks.
        "git commit -m \"$(cat <<'MSG'\nx\nMSG \n)\"",
        # The body never ends.
        "git commit -m \"$(cat <<'MSG'\nx\n)\"",
    ],
)
def test_heredoc_that_bash_reads_differently_is_blocking(command: str) -> None:
    assert a.COMMAND_SUBSTITUTION in blocking(command)


def test_dash_heredoc_ends_at_a_tab_indented_delimiter() -> None:
    command = "git commit -m \"$(cat <<-'MSG'\n\tline\n\tMSG\n)\""
    assert texts(command) == [command]
    assert blocking(command) == ()


# -- powershell blocking constructs ------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "construct"),
    [
        ("Write-Output $(Get-Date)", a.PS_SUBEXPRESSION),
        ('Write-Output "$(Get-Date)"', a.PS_SUBEXPRESSION),
        ("Write-Output @(1,2)", a.PS_ARRAY_SUBEXPRESSION),
        ("& $exe arg", a.PS_CALL_OPERATOR),
        ('& "$env:ProgramFiles\\x\\tool.exe" a', a.PS_CALL_OPERATOR),
        ("& { Remove-Item x }", a.PS_CALL_OPERATOR),
        ("& $tools.Build --release", a.PS_CALL_OPERATOR),
        ("& 'C:\\x\\tool.exe'.Trim()", a.PS_CALL_OPERATOR),
        ("& (Get-Command git) status", a.PS_CALL_OPERATOR),
        ("&", a.PS_CALL_OPERATOR),
        ("Write-Output a`nb", a.PS_BACKTICK),
        ('Write-Output "a`nb"', a.PS_BACKTICK),
        ("iex $code", a.PS_INVOKE_EXPRESSION),
        ("Invoke-Expression 'ls'", a.PS_INVOKE_EXPRESSION),
        ("icacls x --% /grant", a.PS_STOP_PARSING),
        ("ls > $env:TEMP\\files.txt", a.FILE_REDIRECTION),
        ("ls > C:\\files.txt", a.FILE_REDIRECTION),
        ("ls > \\\\server\\share\\files.txt", a.FILE_REDIRECTION),
        ("ls > ..\\files.txt", a.FILE_REDIRECTION),
        ("ls > ~\\files.txt", a.FILE_REDIRECTION),
        ("<# comment #> ls", a.FILE_REDIRECTION),
        ("git status (Remove-Item -Recurse x)", a.PS_EXPRESSION),
        ("Write-Output (Get-Date).Year", a.PS_EXPRESSION),
    ],
)
def test_powershell_blocking(command: str, construct: str) -> None:
    assert construct in blocking(command, "powershell")


@pytest.mark.parametrize(
    "command",
    [
        "dotnet build 2>&1",
        "ls 2>$null",
        "ls *> $null",
        "Write-Output 'it''s $(fine)'",
        'Write-Output "say ""hi"""',
        "Get-ChildItem -Recurse | Select-Object Name",
        "Get-Content x | Out-Null",
        "Get-ChildItem | Where-Object { $_.Length -gt 1 }",
        "Write-Output '(text)'",
        "ls > files.txt",
        "dotnet test *> red-run.log",
        "ls 2> logs\\err.txt",
        "ls >> .\\files.txt",
        '& "C:\\Tools\\build.exe" --release',
        "& 'C:\\Program Files\\Git\\bin\\git.exe' status",
        "& .\\run.cmd test",
        "& C:\\Tools\\build.exe",
        "& 'it''s\\tool.exe'",
        "Get-Item x | & .\\filter.ps1",
    ],
)
def test_powershell_not_blocking(command: str) -> None:
    assert blocking(command, "powershell") == ()


def test_iex_is_matched_as_a_word_only() -> None:
    assert blocking("Write-Output index", "powershell") == ()
    assert blocking("pip install iexplore-tools", "powershell") == ()


def test_dialect_for_tool() -> None:
    assert a.dialect_for_tool("PowerShell") == "powershell"
    assert a.dialect_for_tool("Bash") == "bash"
    assert a.dialect_for_tool(None) == "bash"


# -- words -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "dialect", "expected"),
    [
        ("dotnet test>out.log", "bash", ["dotnet", "test", ">", "out.log"]),
        ("make 2>err.txt", "bash", ["make", "2>", "err.txt"]),
        ("make &>> all.log", "bash", ["make", "&>>", "all.log"]),
        ("make 2>&1", "bash", ["make", "2>&1"]),
        ("sort <in.txt", "bash", ["sort", "<", "in.txt"]),
        ('echo ">" x\\>y', "bash", ["echo", '">"', "x\\>y"]),
        ("dotnet test *>red-run.log", "powershell", ["dotnet", "test", "*>", "red-run.log"]),
    ],
)
def test_words_split_redirection_operators(statement: str, dialect: a.Dialect, expected) -> None:
    assert a.words(statement, dialect) == expected


def test_redirect_words_are_the_file_redirects_only() -> None:
    items = a.words("make 2>err.txt -j 4 >/dev/null 2>&1 > out.log")
    assert items == ["make", "2>", "err.txt", "-j", "4", ">", "/dev/null", "2>&1", ">", "out.log"]
    assert a.redirect_words(items) == {1, 2, 8, 9}


def test_words_keep_quotes_and_group_quoted_text() -> None:
    assert words('git commit -m "hello world"') == ["git", "commit", "-m", '"hello world"']
    assert words("echo 'a b' c") == ["echo", "'a b'", "c"]


def test_words_bash_escaped_space_is_one_word() -> None:
    assert words("ls my\\ dir") == ["ls", "my\\ dir"]
    assert words("ls my\\ dir", "powershell") == ["ls", "my\\", "dir"]
