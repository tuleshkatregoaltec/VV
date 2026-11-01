---
name: crew
description: Plan, delegate, and verify a VV task using GPT scout, builder, and verifier subagents. Use when the user invokes $crew or explicitly asks for the Crew workflow.
---

# Crew for VV

Adapted from https://github.com/maan-iitd2/crew at
`bac9c40b50422d9e1a5eeb60943bc9432a54ffd0`; upstream MIT license is in `LICENSE`.
Use the user's request following `$crew` as the task. `/crew` in ordinary text
also expresses intent to use this workflow; Codex's native skill syntax is `$crew`.

## Planner rules

Keep the upstream pattern: size → scout → brief → scoped workers → independent
verification → evidence. Delegate noisy exploration, but read relevant code yourself
when needed for a sound decision or VV's read-before-write rule.

Read applicable `AGENTS.md`, `development.md`, and `just --list`. Reuse the repository
map and reference links in `CLAUDE.md` as project information; its Claude-specific
tool instructions do not apply. Verify dated branch/status claims against git.
Read the production reference before changes with production implications.
Do not copy these documents into a new ruleset.

Never put secrets in briefs. Preserve pre-existing edits. Workers must not commit,
push, deploy, upload evidence, or call live evaluation models unless authorized by
the user's task. Browser checks should reuse VV's Playwright suite and `just`
recipes. Select installed UI/browser skills only when they help the actual task.

## 1. Size and scout

- **Tiny:** a lookup, known command, or small answer. Skip orchestration overhead;
  handle directly or use one worker, then report the actual check.
- **Idea:** requirements are missing. Ask only questions that materially affect
  the goal, constraints, or success criteria; continue independent discovery.
- **Task:** spawn 1–3 `crew_scout` agents for narrow, independent questions.
  Include the repository path and ask for file/line evidence and uncertainties.

This skill explicitly requests delegation for Task work. Use available subagent
tools, not new user-owned chats. Respect the runtime's concurrency limit; with
four slots including the planner, run at most three children at once.

## 2. Brief and plan

Use the scouts' evidence to write:

```text
Goal:         <outcome>
Found:        <relevant files and facts>
Done when:    <runnable check and expected result, or observable evidence>
Out of scope: <boundaries>
```

Split into the fewest useful pieces, usually 1–3. Show piece, role, model, relevant
installed skills, and dependency. Serialize pieces that touch the same files.
Proceed with already-authorized work. If the user explicitly requested plan approval,
present Go / Change / Cancel and wait; do not impose an extra approval stop otherwise.
Missing information or permissions still require resolution when they block work.

## 3. GPT routing and execution

Project roles live in `.codex/agents/` relative to the VV root:

| Work | Role | Model / effort |
| --- | --- | --- |
| Locate files, read-only reconnaissance | `crew_scout` | `gpt-6-luna` / high |
| Setup, docs, scoped code, debugging | `crew_builder` | `gpt-6.1-sol` / high |
| Independent correctness check | `crew_verifier` | `gpt-6.1-sol` / high |

Keep the planner's selected model. Use only model IDs exposed by the current
runtime. If a listed model is unavailable, inherit the selected model and disclose
the fallback; do not guess aliases or claim a cost saving without measurements.

Where the spawn tool supports custom agent types, select the named role. Where it
only supports a task/message, read the corresponding TOML and include its
`developer_instructions` in the child brief. Apply the model/effort above using
the tool's supported fields. For `collaboration.spawn_agent`, use `fork_turns="none"`
when specifying model/effort, and give the child all necessary context. If model
overrides are unavailable, inherit and report that limitation. If delegation itself
is unavailable, disclose it and perform the workflow serially without claiming an
independent verifier.

Scout/verifier read-only rules are behavioral instructions, not separate sandboxes;
all agents inherit session permissions. Do not weaken those permissions.

Every worker gets a self-contained brief:

```text
OBJECTIVE:  what this piece achieves
CONTEXT:    repository path, findings, relevant instructions and user constraints
SKILLS:     installed skills to read first, or none
BOUNDARIES: owned files, excluded areas, pre-existing changes, external-action limits
CHECK:      command/test/evidence to run and expected outcome
RETURN:     at most 250 words: work done, files changed, actual check output, gaps
```

Run independent pieces concurrently within available slots; batch larger fan-outs.
Wait for results and reuse workers for fixes. Workers do not spawn more agents.

## 4. Verify and report

Send a fresh `crew_verifier` the goal, done-when, changed paths and baseline changes.
It reruns relevant checks and looks for correctness gaps without editing source.
Use at most two delegated fix rounds. If gaps remain, report them clearly and
reassess the approach; never mark incomplete work done or silently discard failures.

Report:

```text
Done:         yes / partly, with remaining work
What changed: files or outputs
Evidence:     checks actually run and short results; skipped/blocked checks
Who did what: pieces, roles, actual models and any fallback
```

Keep context compact with concise checkpoints. If a handoff is needed, preserve
goal, current state, evidence and next step; do not force a new chat merely because
the context compacted.
