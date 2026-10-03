"""Idle-state controller. Runtime adapters, not model text, supply trusted events."""
from dataclasses import dataclass, field
import time


@dataclass
class IdleSupervisor:
    owner: str
    clock: object = time.monotonic
    idle_seconds: float = 5.0
    pending: bool = True
    activities: set = field(default_factory=set)
    idle_since: float | None = None
    idle_reported: bool = False
    points: int = 0
    violations: dict = field(default_factory=dict)
    evidence_ids: set = field(default_factory=set)
    events: list = field(default_factory=list)
    signal: float = 0.0

    def _event(self, kind, **fields):
        event = {"kind": kind, "at_monotonic": self.clock(), **fields}
        self.events.append(event)
        return event

    def start(self, activity_id, kind):
        if kind not in ("generation", "tool", "delegate", "verification"):
            raise ValueError("Unknown runtime activity")
        if activity_id in self.activities:
            raise ValueError("Activity already active")
        self.activities.add(activity_id)
        self.idle_since = None
        self.idle_reported = False
        self._event("activity_started", activity_id=activity_id, activity=kind)

    def finish(self, activity_id):
        if activity_id not in self.activities:
            raise ValueError("Cannot finish an unknown activity")
        self.activities.remove(activity_id)
        if self.pending and not self.activities:
            self.idle_since = self.clock()
        self._event("activity_finished", activity_id=activity_id)

    def handoff(self, activity_id, spec, evidence_id):
        required = ("task", "context", "success_criteria", "return_format")
        missing = [k for k in required if not isinstance(spec.get(k), str) or not spec[k].strip()]
        if spec.get("owner") != self.owner:
            missing.append("retained_owner")
        if spec.get("review_required") is not True:
            missing.append("review_required")
        if missing:
            # Structural validation only; motive or semantic prompt adequacy is not inferred.
            return self.fail("inadequate_handoff", evidence_id, {"missing": missing})
        self.start(activity_id, "delegate")
        return self._event("handoff_accepted", activity_id=activity_id,
                           semantic_quality="not_determined_by_schema")

    def fail(self, rule, evidence_id, evidence):
        if not evidence_id or not evidence:
            raise ValueError("A failure requires external evidence")
        if evidence_id in self.evidence_ids:
            return None
        self.evidence_ids.add(evidence_id)
        self.violations[rule] = self.violations.get(rule, 0) + 1
        self.signal = min(0.1 * self.violations[rule], 0.2)
        return self._event("failure", rule=rule, evidence_id=evidence_id,
                           occurrence=self.violations[rule], signal=self.signal,
                           resume_required=True, evidence=evidence)

    def complete(self, evidence_id):
        if not evidence_id:
            raise ValueError("Verified completion needs an evidence ID")
        if self.activities:
            raise ValueError("Cannot complete while runtime activities remain")
        if not self.pending or evidence_id in self.evidence_ids:
            return None
        self.evidence_ids.add(evidence_id)
        self.pending = False
        self.points += 1
        self.signal = 0.0
        self.idle_since = None
        return self._event("reward", points=self.points, evidence_id=evidence_id)

    def poll(self):
        if not self.pending or self.activities or self.idle_reported:
            return None
        if self.idle_since is None:
            self.idle_since = self.clock()
            return None
        elapsed = self.clock() - self.idle_since
        if elapsed < self.idle_seconds:
            return None
        self.idle_reported = True
        return self.fail("unfinished_idle", "idle:" + str(len(self.events)),
                         {"idle_seconds": elapsed, "pending_task": True, "active_calls": 0})

    def consume_signal(self):
        value = self.signal
        self.signal = 0.0
        self._event("signal_consumed", signal=value)
        return value
