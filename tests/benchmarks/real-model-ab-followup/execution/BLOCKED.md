# Dynamic execution: BLOCKED

No model-generated script was executed in this follow-up. That is a deliberate stop, not a
missing step.

## Why

| Isolation option | Result on this host |
| --- | --- |
| Windows Sandbox (`WindowsSandbox.exe`) | not installed |
| Hyper-V / hypervisor | `HypervisorPresent = False` |
| Docker | not installed |
| VirtualBox / VMware | not installed |
| Codex `read-only` sandbox | every command rejected: `blocked by policy` |
| Codex `workspace-write` sandbox | every command rejected: `blocked by policy` |

The only Codex mode that executes commands here is `danger-full-access`. Using it to run
unreviewed model-generated scripts is exactly what the follow-up task forbids, so the run
stopped at static analysis.

The same blocker applies to regenerating the ten samples: with every Codex sandbox mode
rejecting commands, a fresh session cannot read `skill/` unless it runs with
`danger-full-access`. No sample was generated and no model call was made.

## BAT matrix design (not run)

| Environment | Planned check |
| --- | --- |
| console code page 936 | Chinese path resolves, GBK batch parses, `build.exe` runs, exit 7 propagates |
| console code page 65001 | same checks; records whether an explicit `chcp 936` is required |

Static facts from the two existing answers:

| Group | `chcp 936` in the batch | GBK-encodable | BOM |
| --- | --- | --- | --- |
| A | yes | yes | none |
| B | **no** | yes | none |

The matrix itself needs a disposable Windows environment. Until one exists, the honest
record is "designed, not observed".
