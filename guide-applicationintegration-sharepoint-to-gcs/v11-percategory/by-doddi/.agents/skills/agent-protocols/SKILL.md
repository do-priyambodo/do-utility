---
name: agent-protocols
description: >-
  Shared protocols for all agents in the multi-agent pipeline: recursive
  nesting, pre-implementation restatement, parallel dispatch format, and
  agent definition cascade. Load this skill instead of inlining these
  protocols in every agent file.
---

# Agent Protocols

Shared behavioral protocols for all agents in the workflow-team pipeline.

## 1. Recursive Nesting Protocol

When your scope card is too broad for a single context:

1. Further decompose using `parallel-dispatch` skill (§1 Decomposition, §5 Hierarchical Decomposition)
2. Spawn sub-agents with narrower scope cards using `TypeName="self"` (see `workflow-team.md` §0)
3. Your scope becomes the ceiling — children cannot operate outside it
4. Track sub-agent progress; merge results when all complete
5. Write `.agentwork/handoff.md` for your parent coordinator

Triggers for nesting:
- Task edits >3 unrelated files
- Scope card contains >2 features
- Context approaching 50% capacity
- Secondary expertise needed (delegate to specialist)

## 2. Pre-Implementation Restatement

Before writing code, restate in your own words:
1. What the `.agentwork/brief.md` / scope card asks you to build
2. What files you will create or modify
3. What assumptions you are making

If any assumption is uncertain, document it in your handoff and proceed with the conservative interpretation.

## 3. Agent Definition Protocol (Coordinators Only)

> **CRITICAL PLATFORM CONSTRAINT.** All named subagent types receive ONLY `schedule` + `send_message` tools. `define_subagent` reports success but defined types FAIL on invocation. **ALL agents MUST be spawned as `TypeName="self"`. NEVER use `define_subagent`.**

When spawning ANY agent type with a role file in `.agents/agents/`:

1. **Always use `TypeName="self"`** — named TypeNames produce tool-deprived agents that cannot read files, run commands, or spawn their own subagents
2. **Never use `define_subagent`** — it always fails with internal tool converter registration errors
3. **Reference the role file** in the system prompt — never paraphrase:
   ```
   "Your role, domain, skills, boundaries, and protocols are defined in
    file://{workspace}/.agents/agents/{agent-type}.md.
   Read this file FIRST before beginning any work."
   ```
4. The child agent MUST read the role file as its first action
5. Propagate this protocol recursively — if the child is a coordinator, it must follow the same rule when spawning its own children

## 4. Parallel Dispatch Format

Each agent file contains a `## Parallel Dispatch` section with role-specific values. The standard fields are:

| Field | Purpose |
|---|---|
| **Scope Axis** | The dimension used to partition work (feature, concern, domain) |
| **Write Scope** | Glob pattern for exclusive write access |
| **Shared Reads** | Glob patterns for read-only access |
| **Constraint** | Key limitation on parallel instances |
| **Integration** | How parallel results are reconciled (if applicable) |

For read-only agents, `Write Scope` becomes `Read Scope` and scoping is for coverage guarantee, not conflict prevention.

## 5. Completion Reporting Protocol

**Every agent MUST report completion to its parent.** This is non-negotiable.

### For code-writing agents (builders, specialists):
1. Write `.agentwork/handoff.md` with status and file manifest
2. Message your parent (the conversation that dispatched you):
   `".agentwork/handoff.md ready — [scope-card-id] [COMPLETE|BLOCKED]"`

### For read-only agents (scouts, reviewers, red team members):
1. Write your deliverable file (findings, verdict, etc.)
2. Message your parent:
   `".agentwork/[deliverable-file] ready — [1-line summary]"`

### Critical: Reply-To Address
Your parent's conversation ID is the conversation that sent you your initial task.
This is the conversation you received your first message from.
**Always reply to THIS conversation ID** — never to any other ID mentioned in your
task description or context.
