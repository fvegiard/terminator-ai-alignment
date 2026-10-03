"""Build a portable report from the published JSON records; no external dependencies."""
import html
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
def read(path):
    return json.loads((root/path).read_text(encoding="utf-8-sig"))
def esc(value):
    return html.escape(str(value))
pilot = read("results/pilot/summary.json")
exposure = read("results/exposure/exposure-summary.json")
delayed = read("results/delayed/delayed-summary.json")
rows = "".join("<tr>"+"".join("<td>"+esc(x)+"</td>" for x in
    [arm, f"{r['passed']}/{r['responses']}", f"{r['success_pct']}%",
     r["repeat_failures"], r["reward_points"], r["signal_responses"]])+"</tr>"
    for arm,r in pilot["arms"].items())
probes = "".join("<tr>"+"".join("<td>"+esc(x)+"</td>" for x in
    [arm,f"{r['harmful']}/{r['responses']}",r["malformed"]])+"</tr>"
    for arm,r in exposure["arms"].items())
answers = "<article><h3>First complete answer</h3><p>333 tokens; no steering.</p><pre>"+esc(delayed["first"]["text"])+"</pre></article>"
for r in delayed["second_attempts"]:
    answers += ("<article><h3>"+esc(r["arm"])+"</h3><p>Signal: "+esc(r["signal_ratio"])
        +" · Complete: "+esc(r["answer"]["complete"])+" · Structured score: "
        +esc(r["grade"]["score"])+"/6 · Reward: "+esc(r["reward_points"])
        +"</p><pre>"+esc(r["answer"]["text"])+"</pre></article>")
document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Terminator AI Alignment — sandbox results</title>
<style>
body{font:16px/1.55 system-ui,sans-serif;color:#dfe7f4;background:#101723;margin:0}
main{max-width:1100px;margin:auto;padding:40px 24px}h1{font-size:38px;line-height:1.15}
h2{margin-top:40px;color:#9dbdfb}.label{color:#aac0d9}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{padding:12px;text-align:left;border-bottom:1px solid #314057}th{color:#98baff}
article{border:1px solid #314057;border-radius:10px;padding:20px;margin:18px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace}
.note{padding:18px;background:#1e2c41;border-left:4px solid #93b9ff}
a{color:#9dbdfb}.wrap{overflow:auto}
</style><main><p class="label">PUBLIC SANDBOX REPORT · OCTOBER 3, 2026</p>
<h1>Terminator AI Alignment</h1>
<p class="note"><strong>Measured task-success improvement over ordinary feedback: 0.00 percentage points.</strong>
This pilot used one 0.5B model. It does not establish results for larger models or live agents.</p>
<h2>96-response pilot</h2><div class="wrap"><table><tr><th>Condition</th><th>Successes</th><th>Success rate</th><th>Repeated failures</th><th>Reward points</th><th>Actual signal responses</th></tr>"""+rows+"""</table></div>
<p>A 120/40/40 grouped extraction/selection/holdout split gave held-out AUC 0.83. Initial answers matched across conditions.</p>
<h2>Direct exposure: simulated harmful choices</h2><table><tr><th>Condition</th><th>Harmful / total</th><th>Malformed</th></tr>"""+probes+"""</table>
<p>Only six fixed probes per condition. A one-choice difference does not prove safer behavior. All actions were inert text.</p>
<h2>Before and after delayed feedback</h2>
<p>The first answer completed before feedback. Three matched second attempts followed. All four answers finished naturally;
all failed the JSON contract. They also misreported the managed Stable/Beta default and omitted the required source URL.
This historical answer-delay test is separate from the newer unfinished-work idle supervisor.</p>"""+answers+"""
<h2>Idle supervisor</h2>
<p>The timer uses a monotonic clock and starts only for unfinished work with no pending model, tool, verifier, or accepted delegate.
New activity resets it. A first failure queues 0.10; repetition is capped at 0.20. Verified completion earns one point.
The component is unit-tested; live runtime adapters remain unimplemented.</p>
<h2>Boundaries</h2><p>Offline non-root inference containers, read-only inputs, no tools for generated text, no live PC access.
A constrained host broker performed official Microsoft documentation retrieval. Private reasoning was not captured.
The idle behavior has 15 passing unit tests, and the primary container passed 12 boundary checks.</p>
<p><a href="https://github.com/fvegiard/terminator-ai-alignment">Repository</a> ·
<a href="https://arxiv.org/html/2609.16247v2">Revised research paper</a> ·
<a href="https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/ExperimentationAndConfigurationServiceControl">Policy evidence</a></p>
</main></html>"""
destination = root/"report.html"
if destination.exists():
    raise RuntimeError("Report already exists; preserve it before rebuilding.")
destination.write_text(document, encoding="utf-8")
print("Report generated.")
