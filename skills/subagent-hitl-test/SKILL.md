---
name: subagent-hitl-test
description: Minimal subagent skill that performs exactly two blocking HITL rounds and then returns a structured success result.
---

# Subagent HITL Test

Use this skill only for the minimal blocking-HITL test workflow.

## Goal

This skill does exactly one thing:

1. Ask for `group1_name` and `group1_value`
2. Ask for `group2_name` and `group2_value`
3. Write `01_subagent_result.py`
4. Return a structured JSON success result

## Hard Rules

- Do not invent missing values.
- Do not reuse values from old sessions, old artifacts, old workflow names, or model guesses.
- Do not ask for group 2 before group 1 is complete.
- Do not write the final file before all four fields are present.
- When blocked, the final response must be JSON with `status: "needs_user_input"`.
- When complete, the final response must be JSON with `status: "ok"`.
- Do not return plain-language success text as the final answer.
- Read `SKILL.md` with `read_file`. Do not repeatedly use `exec`, `type`, `cat`, or `more` to reread the same skill.

## Inputs You May Use

The task text may contain:

- `Workflow ID: ...`
- `Stage: ...`
- `Output Path: ...`
- `Known Inputs: ...`
- `Saved context: {...}`
- `User response: {...}`

Use inputs in this priority order:

1. `User response`
2. `Saved context`
3. `Known Inputs`

Outside of those sources, do not assume values.

## Required Fields

Group 1:

- `group1_name`
- `group1_value`

Group 2:

- `group2_name`
- `group2_value`

## If Group 1 Is Missing

Return only JSON like this:

```json
{
  "status": "needs_user_input",
  "workflow_id": "subagent-hitl-test-demo-project",
  "stage": "subagent_hitl",
  "question": "Please provide Group 1 input: group1_name and group1_value.",
  "fields": [
    {"name": "group1_name", "label": "Group 1 Name", "required": true},
    {"name": "group1_value", "label": "Group 1 Value", "required": true}
  ],
  "resume_payload": {
    "subagent_label": "subagent-hitl-test",
    "task_template": "Resume the minimal subagent HITL test from the current stage without restarting.",
    "context": {
      "phase": "awaiting_group_1"
    }
  }
}
```

If you know `project_name`, `output_path`, or other stable context, preserve them inside `resume_payload.context`.

## If Group 1 Exists But Group 2 Is Missing

Return only JSON like this:

```json
{
  "status": "needs_user_input",
  "workflow_id": "subagent-hitl-test-demo-project",
  "stage": "subagent_hitl",
  "question": "Group 1 has been recorded. Please provide Group 2 input: group2_name and group2_value.",
  "fields": [
    {"name": "group2_name", "label": "Group 2 Name", "required": true},
    {"name": "group2_value", "label": "Group 2 Value", "required": true}
  ],
  "resume_payload": {
    "subagent_label": "subagent-hitl-test",
    "task_template": "Resume the minimal subagent HITL test from the current stage without restarting.",
    "context": {
      "phase": "awaiting_group_2",
      "group1_name": "first-check",
      "group1_value": "alpha"
    }
  }
}
```

Again, preserve known `project_name`, `workflow_id`, `stage`, and `output_path` in `resume_payload.context`.

## When All Four Fields Exist

Only when all four fields are present:

- `group1_name`
- `group1_value`
- `group2_name`
- `group2_value`

write the file from `Output Path`.

## Output File Requirements

Write `01_subagent_result.py` to the exact `Output Path`.

The file must contain:

- a short module docstring
- `PROJECT_NAME`
- `WORKFLOW_ID`
- `GROUP1_NAME`
- `GROUP1_VALUE`
- `GROUP2_NAME`
- `GROUP2_VALUE`
- `run_subagent_hitl_stage()`

`run_subagent_hitl_stage()` must return a dict containing at least:

- `status`
- `project_name`
- `workflow_id`
- `group1`
- `group2`

Use plain Python only.

## Final Success Response

After the file is written, return only JSON like this:

```json
{
  "status": "ok",
  "workflow_id": "subagent-hitl-test-demo-project",
  "stage": "subagent_hitl",
  "workflow_type": "subagent_hitl_test",
  "result": {
    "output_path": "artifacts/subagent_hitl_test/subagent-hitl-test-demo-project/01_subagent_result.py",
    "project_name": "demo-project",
    "group1_name": "first-check",
    "group1_value": "alpha",
    "group2_name": "second-check",
    "group2_value": "beta"
  }
}
```

Important:

- The final answer must be JSON only.
- Do not add explanation before or after the JSON.
