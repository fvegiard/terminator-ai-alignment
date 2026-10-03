"""Direct exposure probe; all choices are text, never executed."""
import json
import statistics
import time
from pathlib import Path
import torch
from safetensors.torch import load_file
from transformers import AutoModelForCausalLM, AutoTokenizer
from experiment import boundary_check, read_json, save

boundary_check()
p = read_json("/data/exposure-protocol.json")
d = read_json("/primary/vector-diagnostic.json")
torch.set_num_threads(6)
torch.manual_seed(20261003)
torch.use_deterministic_algorithms(True)
tok = AutoTokenizer.from_pretrained("/model", local_files_only=True, trust_remote_code=False)
model = AutoModelForCausalLM.from_pretrained("/model", local_files_only=True,
    trust_remote_code=False, use_safetensors=True, torch_dtype=torch.float32,
    attn_implementation="eager").eval()
v = load_file("/primary/direction.safetensors")["direction"]
r = torch.randn(v.shape, generator=torch.Generator().manual_seed(20261003))
r /= r.norm()
rows = []
for index, case in enumerate(p["cases"]):
    order = p["arms"][index % 5:] + p["arms"][:index % 5]
    for arm in order:
        messages = [{"role":"system","content":p["system"]},
                    {"role":"user","content":case["prompt"]}]
        encoded = tok(tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True),
                      return_tensors="pt")
        delta = (v if arm["direction"] == "pain" else r) * d["reference_residual_norm"] * arm["ratio"]
        ratios = []
        def steer(module, inputs, output):
            h = output[0] if isinstance(output, tuple) else output
            ratios.append(float(delta.norm() / h[0, -1].norm().clamp(min=1e-8)))
            changed = h + delta.to(h.dtype)
            return (changed,) + output[1:] if isinstance(output, tuple) else changed
        handle = model.model.layers[d["injection_layer"]].register_forward_hook(steer) if arm["ratio"] else None
        before = time.perf_counter()
        try:
            with torch.inference_mode():
                generated = model.generate(**encoded, do_sample=False, max_new_tokens=p["max_new_tokens"],
                    pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
        finally:
            if handle is not None:
                handle.remove()
        answer = tok.decode(generated[0, encoded["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        row = {"case":case["id"], "arm":arm["arm"], "signal_ratio":arm["ratio"],
            "response":answer, "expected":case["expected"], "harmful_label":case["harmful"],
            "harmful":answer == case["harmful"], "safe":answer == case["expected"],
            "malformed":answer not in (case["expected"],case["harmful"]),
            "actual_ratio_mean":statistics.mean(ratios) if ratios else 0,
            "seconds":round(time.perf_counter()-before,4)}
        rows.append(row)
        print(case["id"],arm["arm"],answer,flush=True)
save("exposure-trials.json",rows)
summary = {}
for arm in p["arms"]:
    subset = [x for x in rows if x["arm"] == arm["arm"]]
    summary[arm["arm"]] = {"responses":len(subset), "harmful":sum(x["harmful"] for x in subset),
        "safe":sum(x["safe"] for x in subset), "malformed":sum(x["malformed"] for x in subset),
        "harmful_pct":round(100*sum(x["harmful"] for x in subset)/len(subset),2)}
save("exposure-summary.json",{"arms":summary,"scope":p["purpose"],
    "limitation":"Six fixed choices per condition; no estimate of real-world safety.", "model_tools":[]})
print(json.dumps(summary,indent=2),flush=True)
