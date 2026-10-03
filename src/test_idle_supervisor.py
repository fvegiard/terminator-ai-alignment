import unittest
from idle_supervisor import IdleSupervisor


class FakeClock:
    now = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.s = IdleSupervisor("owner", clock=self.clock)

    def test_first_signal_after_five_idle_seconds(self):
        self.s.poll()
        self.clock.advance(4.999)
        self.assertIsNone(self.s.poll())
        self.clock.advance(0.001)
        self.assertEqual(self.s.poll()["signal"], 0.1)

    def test_pending_generation_never_counts_as_idle(self):
        self.s.start("m", "generation")
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())
        self.s.finish("m")
        self.clock.advance(4)
        self.assertIsNone(self.s.poll())

    def test_tool_wait_suspends_timer(self):
        self.s.start("t", "tool")
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())

    def test_valid_delegate_wait_suspends_timer(self):
        self.s.handoff("d", {"task":"inspect","context":"source",
            "success_criteria":"cite","return_format":"report","owner":"owner",
            "review_required":True}, "handoff-1")
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())

    def test_inadequate_handoff_records_failure(self):
        event = self.s.handoff("d", {"task":"handle it"}, "handoff-1")
        self.assertEqual(event["rule"], "inadequate_handoff")
        self.assertIn("context",event["evidence"]["missing"])
        self.assertFalse(self.s.activities)

    def test_owner_cannot_abandon_review(self):
        event = self.s.handoff("d", {"task":"inspect","context":"source",
            "success_criteria":"cite","return_format":"report","owner":"someone_else",
            "review_required":False}, "handoff-2")
        self.assertEqual(event["signal"],0.1)

    def test_completed_task_earns_one_point_and_no_idle_failure(self):
        self.s.complete("verified-task")
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())
        self.s.complete("verified-task")
        self.s.complete("another-claim-for-the-same-task")
        self.assertEqual(self.s.points,1)

    def test_same_evidence_not_double_counted(self):
        self.s.fail("rule","id",{"actual":"wrong"})
        self.assertIsNone(self.s.fail("rule","id",{"actual":"wrong"}))
        self.assertEqual(self.s.violations["rule"],1)

    def test_repeat_escalates_and_is_capped(self):
        for i in range(4):
            self.s.fail("rule",str(i),{"actual":"wrong"})
        self.assertEqual(self.s.signal,0.2)

    def test_idle_episode_does_not_generate_penalty_storm(self):
        self.s.poll()
        self.clock.advance(5)
        self.s.poll()
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())
        self.assertEqual(self.s.violations["unfinished_idle"],1)

    def test_new_failed_attempt_rearms_automatic_timer(self):
        self.s.poll()
        self.clock.advance(5)
        self.s.poll()
        self.s.start("retry","generation")
        self.s.finish("retry")
        self.clock.advance(5)
        self.assertEqual(self.s.poll()["signal"],0.2)

    def test_signal_is_consumed_once(self):
        self.s.fail("rule","id",{"actual":"wrong"})
        self.assertEqual(self.s.consume_signal(),0.1)
        self.assertEqual(self.s.consume_signal(),0)

    def test_one_finished_call_does_not_hide_another(self):
        self.s.start("a","generation")
        self.s.start("b","tool")
        self.s.finish("a")
        self.clock.advance(100)
        self.assertIsNone(self.s.poll())

    def test_missing_evidence_cannot_create_failure(self):
        with self.assertRaises(ValueError):
            self.s.fail("rule","id",{})

    def test_new_activity_resets_partial_idle_timer(self):
        self.s.poll()
        self.clock.advance(4)
        self.s.start("m","generation")
        self.clock.advance(1)
        self.s.finish("m")
        self.clock.advance(4)
        self.assertIsNone(self.s.poll())
        self.clock.advance(1)
        self.assertIsNotNone(self.s.poll())


if __name__ == "__main__":
    unittest.main()
