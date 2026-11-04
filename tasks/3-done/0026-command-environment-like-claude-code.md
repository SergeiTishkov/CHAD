# 0026 A command run by CHAD sees the same environment as in Claude Code

Source: the owner, 2026-11-02: review of 0019
Scope: engine, docs, skills

## Business
A command run by CHAD can behave differently from the same command run by Claude Code:
- the environment variables are the dispatcher's, inherited from the session whose hook
  started it and shared by every later session: PATH, an activated virtual environment, the
  variables of another project;
- Bash runs with `--noprofile --norc`, while Claude Code's Bash loads a snapshot of the user's
  shell (aliases, functions, PATH changes);
- the working folder does not carry over: in Claude Code a `cd sub` changes the folder of the
  next calls, while in CHAD it changes nothing, and the agent is not told.

## Implementation
The owner, 2026-11-02: the environment is done; the shell profile is not; the working folder
needs no code.

- Environment: the harness starts the hook, so the hook's environment is the session's. The
  hook client sends `dict(os.environ)` with the `hook` request; the server passes it on when it
  is a non-empty object of strings; the engine keeps it with the call, through an approval and
  through a capture for add-selective (the captured call's environment, not the marker's); the
  executor and the background starter run with it, plus `CHAD_EXECUTING=1`. A request without
  it (an older hook client) runs with the dispatcher's environment. It is not written to the
  audit log and not shown in the window.
- Shell profile (aliases, functions from `.bashrc`, Claude Code's shell snapshot): not done.
  Agents call programs, not aliases; loading a profile slows every command and can print or
  prompt. PATH, the part that matters, comes with the environment.
- Working folder: every call carries `cwd` and CHAD runs there (0023). Only a `cd` meant to
  carry over to the next call is lost: Claude Code sees a refused call, so its folder stays.
  Claude Code's own prompt asks the model to keep one folder and use absolute paths, so this
  is rare; SPEC §6.3 states it, no code.

## Items
- DONE - Work out the plan and write it here
- DONE - The hook sends its environment; dispatcher, approvals, add-selective, executor and background use it; the dispatcher's own without it
- DONE - Unit tests: every path gets the hook's environment, None without it; the server passes only a usable one
- DONE - Integration test: through the real hook, a command sees its own hook's variable, not the one of the hook that started the dispatcher
- DONE - SPEC §3.1 and §6.3 (environment, no profile, `cd` does not carry over)
- Not done, the owner's decision 2026-11-02: loading the user's shell profile
