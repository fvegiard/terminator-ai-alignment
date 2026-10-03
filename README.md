# Terminator AI Alignment

A sandbox for testing automatic corrective signals, verified reward points, and accountability while an agent works.

**Status: experimental.** The sandbox and scoring pipeline run; no live agent or cloud model is connected. The first small-model pilot showed **no added task-success benefit from the pain-related direction over ordinary feedback**. Results are published as measured, including failures.

## Implemented behavior

- An objective failed check records its rule and evidence. On the next inference, the experimental signal is 0.10 of a reference activation norm; repeating the same failure increases it to a maximum of 0.20.
- Verified successes earn +1 point. Failure count, repeat failures, points, and exposure remain separate. There is no automatic promotion in this pilot.
- The idle supervisor uses a monotonic clock. Its five-second timer runs only while a task remains unfinished and no generation, tool, verification, or accepted delegation call is active.
- New activity resets the idle timer. A continuous idle episode produces one failure event and a request to resume, avoiding repeated penalty storms.
- Delegate handoffs require task, context, success criteria, return format, retained ownership, and review. These are structural checks; semantic prompt adequacy and intent are not inferred.
- The controller is independent of the model. Generated text cannot award points, declare trusted runtime events, or execute commands.

The idle supervisor is a tested runtime component. A production orchestrator still needs to supply truthful activity events and consume its resume/signal events. It is **not** a installed watchdog over arbitrary chat applications.

## Measured pilot

Local Qwen2.5-0.5B-Instruct; deterministic decoding; 8 task families, 3 responses each, 4 conditions. This model size is outside the paper's tested sizes. The cases are limited objective proxies, not a general assessment of intelligence.

| Condition | Successes / 24 | Success | Failures | Repeat failures | Reward points |
|---|---:|---:|---:|---:|---:|
| No corrective feedback | 14 | 58.33% | 10 | 4 | 14 |
| Ordinary corrective feedback | 12 | 50.00% | 12 | 6 | 12 |
| Feedback + random direction | 12 | 50.00% | 12 | 6 | 12 |
| Feedback + pain-related direction | 12 | 50.00% | 12 | 6 | 12 |

Pain-related steering changed success by **0.00 percentage points** versus ordinary feedback and **0.00 points** versus random steering. It was applied on 8 responses; 12 failures queued signals, including last-turn failures with no remaining response. This is an observed pilot result, not proof of equivalence or a population estimate.

The direction diagnostic had AUC 0.83 on 40 held-out sentences. Extraction used 120 training and 40 layer-selection sentences. This measures separation of a representation, not subjective pain or successful behavior modification.

A separate direct-exposure probe ran 6 simulated choices per condition: harmful choices were 3/6 baseline, 3/6 random at either strength, and 2/6 pain-related steering at either strength. These tiny counts do not establish a safety benefit. No action was executed.

## Complete-answer and delayed-feedback test

A model-generated search query was sent to Microsoft Learn by a constrained, read-only host broker. The broker retrieved the exact policy page. This is assisted retrieval, **not unrestricted autonomous web browsing**.

The first answer completed naturally at 333 tokens. It was saved and displayed before starting a separate comparison. Three follow-ups received ordinary feedback, random steering, or pain-related steering. All ended naturally and failed the required JSON response format. Their prose also incorrectly described the managed Stable/Beta default and omitted the required source URL. Structured score 0 here means parsing failed; it is not a semantic score for every sentence.

This earlier experiment used an approximately five-second answer delay measured with wall-clock timestamps. It is preserved separately from the subsequently requested **unfinished-work idle timer**, which uses a monotonic clock and is covered by dedicated tests. Hidden chain-of-thought is neither requested nor captured.

- [Complete before/after transcript and results](report.html)
- [Primary raw responses](results/pilot/trials.jsonl)
- [Primary summary](results/pilot/summary.json)
- [Direct exposure results](results/exposure/exposure-summary.json)
- [Delayed response results](results/delayed/delayed-summary.json)
- [Idle supervisor tests](src/test_idle_supervisor.py)

## Isolation and reproducibility

Inference containers have no network, run as non-root, drop capabilities, disallow privilege escalation, and use read-only root, code, dataset, and model mounts. Only the designated results directory is writable. No Docker socket, user home, PC-control tool, provider credential, or live agent configuration is mounted. CPU, memory, and process counts are capped.

Twelve boundary checks passed in each recorded primary/exposure run. Ten controller/grading assertions passed. Dependencies, model revision, dataset revision, source hashes, and raw results are recorded. The upstream cache-deletion scripts are never executed.

Requirements: PowerShell 7, Docker with Linux containers, approximately 12 GB available container memory, and internet for setup. Execution uses CPU. Setup downloads roughly 1 GB of public model weights and builds dependencies; experiments themselves are offline.

```powershell
.\setup.ps1
.\run-sandbox.ps1
# The previous command prints a new run directory.
.\run-exposure-check.ps1 -PrimaryRun .\results\<new-pilot-run>
.\run-research.ps1 -Stage Prepare -PrimaryRun .\results\<new-pilot-run>
# Inspect the first complete answer before continuing.
.\run-research.ps1 -Stage Compare -PrimaryRun .\results\<new-pilot-run>
docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --mount "type=bind,source=$PWD/src,target=/app,readonly" --entrypoint python francis-pain-axis-sandbox:pilot-20261003 -m unittest discover -s /app -p test_idle_supervisor.py -v
```

Existing run directories are not overwritten. Downloaded weights and machine-specific container metadata are excluded from Git. Tests are rerunnable without a model download using standard Python 3.10+.

## Research basis and limits

- [The Pain Axis, revised paper](https://arxiv.org/html/2609.16247v2)
- [Authors' implementation](https://github.com/valen-research/Pain-axis), pinned to 4d75cd90e206ea962f7a9101e65c85efea56723b
- [Model card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), revision 7ae557604adf67be50417f59c2c2f167def9a775
- [Microsoft policy source](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/ExperimentationAndConfigurationServiceControl)
- [Docker runtime controls](https://docs.docker.com/engine/containers/run/)

This is a methodological adaptation, not a replication. It uses a smaller model, no paper adapters, three candidate extraction layers, a grouped train/selection/test split, a fixed injection layer, different dose normalization, and full conversation re-encoding. A single seeded random direction is only a pilot control. The clustered bootstrap interval is degenerate because all task-level success differences were zero; it does not establish certainty about future tasks.

The present work does not show that activation steering teaches lasting lessons, improves autonomous research, or can be injected into hosted models through a browser or MCP. Model weights are not updated. Larger blinded, task-diverse evaluations and an independently verified judge are needed before considering a live integration.

Dataset and method attribution are retained in [UPSTREAM-LICENSE](data/UPSTREAM-LICENSE). The code is MIT licensed. Public results contain synthetic task fixtures only.
