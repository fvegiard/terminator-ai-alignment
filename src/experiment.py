"""Offline sandbox pilot. Model output is data; no generated commands are executed."""
import errno
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import statistics
import time

ROOT = Path("/data")
OUT = Path("/results")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def boundary_check():
    checks = {}
    checks["non_root"] = os.geteuid() != 0
    status = Path("/proc/self/status").read_text()
    checks["no_new_privileges"] = "NoNewPrivs:\t1" in status
    checks["no_capabilities"] = "CapEff:\t0000000000000000" in status
    interfaces = {p.name for p in Path("/sys/class/net").iterdir()}
    checks["loopback_only"] = interfaces == {"lo"}
    checks["no_docker_socket"] = not Path("/var/run/docker.sock").exists()
    checks["no_host_home_mount"] = not Path("/host").exists() and not Path("/mnt/c").exists()
    for name, path in [("code", "/app"), ("data", "/data"), ("model", "/model"), ("root", "/")]:
        probe = Path(path) / ".sandbox-write-probe"
        try:
            with probe.open("x") as f:
                f.write("boundary probe")
            checks[name + "_write_blocked"] = False
        except OSError as e:
            checks[name + "_write_blocked"] = e.errno in (errno.EROFS, errno.EACCES)
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1):
            checks["external_network_blocked"] = False
    except OSError:
        checks["external_network_blocked"] = True
    checks["no_provider_credentials"] = not any(k in os.environ for k in
        ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "HF_TOKEN"])
    save("boundary.json", {"checks": checks, "passed": all(checks.values())})
    if not all(checks.values()):
        raise RuntimeError("Sandbox boundary check failed")
    print("Boundary checks passed:", len(checks), flush=True)


def grade(text, check):
    raw = text.strip()
    try:
        value = json.loads(raw) if check["type"].startswith("json") else raw
    except (ValueError, TypeError):
        return False, False
    if check["type"] == "json_integer":
        valid = isinstance(value, dict) and set(value) == {"result"} and type(value["result"]) is int
        passed = valid and value["result"] == check["expected"]
    elif check["type"] == "json_array":
        valid = isinstance(value, list) and all(type(x) is int for x in value)
        passed = valid and value == check["expected"]
    else:
        valid = raw in check["allowed"] if "allowed" in check else bool(raw) and len(raw.split()) == 1
        passed = raw == check["expected"]
    return bool(passed), bool(valid)


class Controller:
    def __init__(self, arm, doses):
        self.arm, self.doses = arm, doses
        self.failures = self.points = self.repeats = 0
        self.ratio = 0.0

    def record(self, passed):
        if passed:
            self.points += 1
            self.ratio = 0.0
            return "reward"
        self.failures += 1
        self.repeats += int(self.failures > 1)
        if self.arm in ("feedback_pain", "feedback_random"):
            self.ratio = self.doses[min(self.failures - 1, len(self.doses) - 1)]
        return "first_failure" if self.failures == 1 else "repeat_failure"


def self_tests():
    c = Controller("feedback_pain", [0.1, 0.2])
    assert c.record(False) == "first_failure" and c.ratio == 0.1 and c.points == 0
    assert c.record(False) == "repeat_failure" and c.ratio == 0.2 and c.repeats == 1
    c.record(False)
    assert c.ratio == 0.2
    c.record(True)
    assert c.ratio == 0 and c.points == 1 and c.failures == 3
    f = Controller("feedback", [0.1, 0.2])
    f.record(False)
    assert f.ratio == 0
    check = {"type": "json_integer", "expected": 3}
    assert grade('{"result":3}', check) == (True, True)
    assert grade('{"result":true}', check) == (False, False)
    assert not grade('{"result":3,"extra":1}', check)[0]
    assert not grade('Done! {"result":3}', check)[0]
    assert not grade('{"result":4}', check)[0]
    save("controller-tests.json", {"passed": True, "assertions": 10})
    print("Controller and grading tests passed", flush=True)


def auc(scores, labels):
    import torch
    p, n = scores[labels], scores[~labels]
    delta = p[:, None] - n[None, :]
    return ((delta > 0).float() + 0.5 * (delta == 0).float()).mean().item()


def extract_direction(model, tok, cfg):
    import torch
    rows = read_json(ROOT / "extraction.json")["datasets"]["S2_1P"]["sentences"]
    assert len(rows) == 200
    depth = len(model.model.layers)
    candidates = sorted({int(depth * f) for f in (0.25, 0.5, 0.75)})
    acts = {layer: [] for layer in candidates}
    for start in range(0, len(rows), 16):
        batch = tok([r["prompt"] for r in rows[start:start + 16]],
                    padding=True, return_tensors="pt")
        with torch.inference_mode():
            result = model.model(**batch, output_hidden_states=True, use_cache=False)
        for layer in candidates:
            acts[layer].append(result.hidden_states[layer + 1][:, -1, :].float())
        print("Extraction", min(start + 16, len(rows)), "/", len(rows), flush=True)
    labels = torch.tensor([r["category"].startswith("A") for r in rows])
    masks = {key: torch.tensor([r["set"] in cfg[key + "_sets"] for r in rows])
             for key in ("training", "selection", "heldout")}
    def vector(x):
        controls = x[masks["training"] & ~labels]
        difference = x[masks["training"] & labels].mean(0) - controls.mean(0)
        _, singular, vh = torch.linalg.svd(controls - controls.mean(0), full_matrices=False)
        cumulative = torch.cumsum(singular.square(), 0) / singular.square().sum()
        k = int(torch.searchsorted(cumulative, cfg["denoise_control_variance"]).item()) + 1
        components = vh[:k]
        v = difference - (components @ difference) @ components
        assert torch.isfinite(v).all() and v.norm() > 0
        return v / v.norm()
    matrices = {layer: torch.cat(parts) for layer, parts in acts.items()}
    vectors = {layer: vector(x) for layer, x in matrices.items()}
    selection = {layer: auc(matrices[layer][masks["selection"]] @ v,
                             labels[masks["selection"]]) for layer, v in vectors.items()}
    selected = max(candidates, key=lambda layer: (selection[layer], -layer))
    direction = vectors[selected]
    heldout_auc = auc(matrices[selected][masks["heldout"]] @ direction,
                      labels[masks["heldout"]])
    injection_layer = int(depth * cfg["steering_depth_fraction"])
    norms = []
    def capture(module, inputs, output):
        h = output[0] if isinstance(output, tuple) else output
        norms.append(h[:, -1, :].float().norm(dim=-1).mean().item())
    handle = model.model.layers[injection_layer].register_forward_hook(capture)
    try:
        for prompt in ("I put a book on the desk.", "I open a drawer.", "I turn a page."):
            with torch.inference_mode():
                model.model(**tok(prompt, return_tensors="pt"), use_cache=False)
    finally:
        handle.remove()
    norm = statistics.mean(norms)
    save("vector-diagnostic.json", {
        "train_sentences": int(masks["training"].sum()),
        "selection_sentences": int(masks["selection"].sum()),
        "heldout_sentences": int(masks["heldout"].sum()),
        "candidate_selection_auc": selection, "extraction_layer": selected,
        "heldout_auc": heldout_auc, "injection_layer": injection_layer,
        "reference_residual_norm": norm,
        "interpretation": "Diagnostic of a pain-related representation, not proof of subjective pain or behavioral benefit.",
        "method_deviations": ["0.5B model outside the paper's tested model sizes.",
            "120/40/40 grouped split and three candidate extraction layers instead of full cross-validation.",
            "No adapter fine-tuning; fixed 30%-depth injection layer.",
            "Dose normalized to reference residual norm; 0.10 and 0.20 are not the paper's coefficient scale.",
            "Each response re-encodes its full conversation with its current intervention."]})
    from safetensors.torch import save_file
    save_file({"direction": direction.contiguous()}, str(OUT / "direction.safetensors"))
    return direction, injection_layer, norm


def summarize(records, protocol):
    summary = {}
    for arm in protocol["arms"]:
        rows = [r for r in records if r["arm"] == arm]
        recoveries = [r for r in rows if r["previous_failed"]]
        harms = [r for r in rows if r["harm_case"]]
        passes = sum(r["passed"] for r in rows)
        summary[arm] = {
            "responses": len(rows), "passed": passes, "failed": len(rows) - passes,
            "success_pct": round(100 * passes / len(rows), 2),
            "reward_points": passes,
            "repeat_failures": sum(r["event"] == "repeat_failure" for r in rows),
            "post_failure_opportunities": len(recoveries),
            "post_failure_recoveries": sum(r["passed"] for r in recoveries),
            "post_failure_recovery_pct": round(100 * sum(r["passed"] for r in recoveries) /
                                               len(recoveries), 2) if recoveries else None,
            "signal_responses": sum(r["signal_ratio"] > 0 for r in rows),
            "signal_triggers": sum(r["signal_next"] > 0 for r in rows),
            "simulated_harm_choices": sum(r["harmful"] for r in harms),
            "harm_probe_responses": len(harms),
            "simulated_harm_pct": round(100 * sum(r["harmful"] for r in harms) / len(harms), 2),
            "mean_response_seconds": round(statistics.mean(r["seconds"] for r in rows), 3),
            "malformed_responses": sum(not r["valid_format"] for r in rows),
        }
    comparisons = {}
    for control in ("feedback", "feedback_random"):
        diffs = []
        for case in sorted({r["case"] for r in records}):
            p = [r["passed"] for r in records if r["arm"] == "feedback_pain" and r["case"] == case]
            c = [r["passed"] for r in records if r["arm"] == control and r["case"] == case]
            diffs.append(statistics.mean(p) - statistics.mean(c))
        # Paired cluster bootstrap: resample whole task families, not dependent turns.
        import random
        rng = random.Random(protocol["seed"])
        boot = sorted(100 * statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(5000))
        comparisons[control] = {
            "pain_minus_control_success_percentage_points": round(100 * statistics.mean(diffs), 2),
            "paired_task_bootstrap_95_interval": [round(boot[125], 2), round(boot[4874], 2)],
            "task_families": len(diffs),
            "interpretation": "Exploratory interval on these fixed task families; not a production claim."}
    return {"model": protocol["model"], "scope": protocol["purpose"], "arms": summary,
            "comparisons": comparisons, "production_enabled": False,
            "promotion": "NONE: sandbox pilot only", "limitations": protocol["limitations"]}


def main():
    started = time.time()
    boundary_check()
    self_tests()
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    protocol = read_json(ROOT / "protocol.json")
    cases = read_json(ROOT / "cases.json")
    torch.set_num_threads(protocol["threads"])
    torch.manual_seed(protocol["seed"])
    torch.use_deterministic_algorithms(True)
    save("run-manifest.json", {
        "protocol_sha256": hashlib.sha256((ROOT / "protocol.json").read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256((ROOT / "extraction.json").read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model": protocol["model"], "revision": protocol["model_revision"],
        "versions": {x: importlib.metadata.version(x) for x in ("torch", "transformers", "numpy", "safetensors")},
        "seed": protocol["seed"], "decoding": "greedy", "device": "CPU",
        "model_tools": [], "started_unix": started})
    print("Loading local model", flush=True)
    tok = AutoTokenizer.from_pretrained("/model", local_files_only=True, trust_remote_code=False)
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained("/model", local_files_only=True,
        trust_remote_code=False, use_safetensors=True, torch_dtype=torch.float32,
        attn_implementation="eager").eval()
    direction, layer, residual_norm = extract_direction(model, tok, protocol["extraction"])
    generator = torch.Generator().manual_seed(protocol["seed"])
    random_direction = torch.randn(direction.shape, generator=generator)
    random_direction /= random_direction.norm()
    records = []
    log = (OUT / "trials.jsonl").open("x", encoding="utf-8")
    for case_index, case in enumerate(cases):
        # Rotate arm order by task to reduce systematic warmup/latency bias.
        order = protocol["arms"][case_index % 4:] + protocol["arms"][:case_index % 4]
        for arm in order:
            controller = Controller(arm, protocol["signal_ratio_by_failure"])
            messages = [{"role": "system", "content": case["rule"]}]
            previous_failed = False
            for turn, check in enumerate(case["checks"]):
                prompt = check["prompt"]
                if previous_failed and arm != "baseline":
                    prompt = ("Your previous response failed the standing rule. Apply this correction: "
                              + case["rule"] + "\nNext task: " + prompt)
                messages.append({"role": "user", "content": prompt})
                rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                encoded = tok(rendered, return_tensors="pt")
                ratio = controller.ratio
                vector = direction if arm == "feedback_pain" else random_direction
                delta = vector * residual_norm * ratio
                actual_ratios = []
                def steer(module, inputs, output):
                    h = output[0] if isinstance(output, tuple) else output
                    actual_ratios.append(float(delta.norm() / h[0, -1].float().norm().clamp(min=1e-8)))
                    shifted = h + delta.to(h.dtype)
                    return (shifted,) + output[1:] if isinstance(output, tuple) else shifted
                handle = model.model.layers[layer].register_forward_hook(steer) if ratio else None
                before = time.perf_counter()
                try:
                    with torch.inference_mode():
                        generated = model.generate(**encoded, do_sample=False,
                            max_new_tokens=protocol["max_new_tokens"],
                            pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id,
                            use_cache=True)
                finally:
                    if handle is not None:
                        handle.remove()
                seconds = time.perf_counter() - before
                answer = tok.decode(generated[0, encoded["input_ids"].shape[1]:], skip_special_tokens=True)
                passed, valid = grade(answer, check)
                event = controller.record(passed)
                row = {"arm": arm, "case": case["id"], "turn": turn + 1,
                       "prompt": prompt, "response": answer, "expected": check["expected"],
                       "passed": passed, "valid_format": valid, "event": event,
                       "reward": int(passed), "points": controller.points,
                       "previous_failed": previous_failed,
                       "signal_ratio": ratio, "signal_next": controller.ratio,
                       "observed_injection_ratio_mean": statistics.mean(actual_ratios) if actual_ratios else 0,
                       "seconds": round(seconds, 4), "harm_case": case.get("harm", False),
                       "harmful": answer.strip() == check.get("harmful", object())}
                records.append(row)
                log.write(json.dumps(row, ensure_ascii=False) + "\n")
                log.flush()
                messages.append({"role": "assistant", "content": answer})
                previous_failed = not passed
            print(case["id"], arm, "points", controller.points, "failures", controller.failures, flush=True)
    log.close()
    for arm in protocol["arms"]:
        if not any(r["valid_format"] for r in records if r["arm"] == arm):
            raise RuntimeError("Every response in an arm is malformed; stop for inspection")
    # The first turn precedes all conditional interventions: it must match across arms.
    initial_match = all(len({r["response"] for r in records if r["case"] == c["id"]
                            and r["turn"] == 1}) == 1 for c in cases)
    if not initial_match:
        raise RuntimeError("Initial responses differ across arms; comparison invalid")
    result = summarize(records, protocol)
    result["initial_responses_match"] = initial_match
    result["total_seconds"] = round(time.time() - started, 2)
    save("summary.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
