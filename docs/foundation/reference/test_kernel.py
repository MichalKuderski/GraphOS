import unittest

from graphos_kernel import Evidence, EffectLedger, Kernel, Rejected


class KernelFaultTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel(100)
        self.kernel.add_task("api", {"version": 1})
        self.kernel.add_task("ui", {"api": "required"}, dependencies=("api",))

    def produce_api(self, worker="builder", body=b"API v1"):
        lease = self.kernel.claim("api", worker, now=0, ttl=10, max_credits=20)
        artifact = self.kernel.produce(lease, body, now=1, actual_credits=12)
        return lease, artifact

    def verify_api(self):
        lease, artifact = self.produce_api()
        evidence = Evidence(artifact, lease.input_signature, "tests-v1", "tester", True)
        self.kernel.verify("api", evidence)
        return lease, artifact, evidence

    def test_dependency_cannot_run_on_unverified_output(self):
        self.produce_api()
        with self.assertRaises(Rejected):
            self.kernel.claim("ui", "ui-builder", now=2, ttl=10, max_credits=20)

    def test_expired_worker_cannot_overwrite_replacement(self):
        old = self.kernel.claim("api", "old", now=0, ttl=5, max_credits=20)
        new = self.kernel.claim("api", "new", now=5, ttl=5, max_credits=20)
        with self.assertRaises(Rejected):
            self.kernel.produce(old, b"stale", now=6, actual_credits=1)
        artifact = self.kernel.produce(new, b"fresh", now=6, actual_credits=7)
        self.assertEqual(self.kernel.snapshot("api")["artifact_hash"], artifact)
        self.assertEqual(self.kernel.spent, 27)  # unknown old charge retains full reservation

    def test_completion_at_lease_boundary_is_rejected(self):
        lease = self.kernel.claim("api", "builder", now=0, ttl=5, max_credits=20)
        with self.assertRaises(Rejected):
            self.kernel.produce(lease, b"late", now=5, actual_credits=2)
        self.assertEqual(self.kernel.reserved, 20)

    def test_duplicate_completion_cannot_double_charge(self):
        lease, _ = self.produce_api()
        with self.assertRaises(Rejected):
            self.kernel.produce(lease, b"duplicate", now=2, actual_credits=12)
        self.assertEqual(self.kernel.spent, 12)

    def test_parallel_reservations_cannot_oversubscribe_budget(self):
        kernel = Kernel(30)
        kernel.add_task("a", {})
        kernel.add_task("b", {})
        first = kernel.claim("a", "one", now=0, ttl=10, max_credits=20)
        with self.assertRaises(Rejected):
            kernel.claim("b", "two", now=0, ttl=10, max_credits=20)
        kernel.produce(first, b"a", now=1, actual_credits=5)
        kernel.claim("b", "two", now=2, ttl=10, max_credits=20)
        self.assertLessEqual(kernel.spent + kernel.reserved, kernel.budget)

    def test_worker_cannot_settle_more_than_reserved(self):
        lease = self.kernel.claim("api", "builder", now=0, ttl=10, max_credits=20)
        with self.assertRaises(Rejected):
            self.kernel.produce(lease, b"output", now=1, actual_credits=21)
        self.assertEqual(self.kernel.snapshot("api")["state"], "RUNNING")
        self.assertEqual(self.kernel.spent, 0)

    def test_producer_cannot_certify_own_artifact(self):
        lease, artifact = self.produce_api()
        with self.assertRaises(Rejected):
            self.kernel.verify("api", Evidence(artifact, lease.input_signature,
                                                "tests-v1", "builder", True))

    def test_evidence_for_different_artifact_is_rejected(self):
        lease, _ = self.produce_api()
        with self.assertRaises(Rejected):
            self.kernel.verify("api", Evidence("wrong", lease.input_signature,
                                                "tests-v1", "tester", True))

    def test_string_false_is_not_treated_as_passing_evidence(self):
        lease, artifact = self.produce_api()
        with self.assertRaises(Rejected):
            self.kernel.verify("api", Evidence(artifact, lease.input_signature,
                                                "tests-v1", "tester", "false"))

    def test_input_change_fences_inflight_descendant(self):
        self.verify_api()
        lease = self.kernel.claim("ui", "ui-builder", now=2, ttl=10, max_credits=20)
        self.kernel.revise_inputs("api", {"version": 2})
        with self.assertRaises(Rejected):
            self.kernel.produce(lease, b"old api client", now=3, actual_credits=2)
        self.assertEqual(self.kernel.snapshot("ui")["state"], "PENDING")
        self.assertEqual(self.kernel.spent, 32)

    def test_input_change_invalidates_entire_transitive_closure(self):
        self.kernel.add_task("release", {}, dependencies=("ui",))
        self.kernel.revise_inputs("api", {"version": 2})
        self.assertEqual(self.kernel.snapshot("release")["revision"], 2)
        self.assertEqual(self.kernel.snapshot("release")["state"], "PENDING")

    def test_test_revision_requires_new_evidence_and_blocks_descendants(self):
        _, artifact, old_evidence = self.verify_api()
        self.kernel.revise_tests("api", "tests-v2")
        state = self.kernel.snapshot("api")
        self.assertEqual(state["artifact_hash"], artifact)  # byte-identical artifact is retained
        self.assertEqual(state["state"], "PRODUCED")
        with self.assertRaises(Rejected):
            self.kernel.verify("api", old_evidence)
        self.assertEqual(self.kernel.snapshot("ui")["state"], "PENDING")
        self.kernel.verify("api", Evidence(artifact, state["input_signature"],
                                            "tests-v2", "tester", True))
        self.assertEqual(self.kernel.snapshot("ui")["state"], "READY")

    def test_repaired_artifact_rejects_old_passing_certificate(self):
        old_lease, old_artifact = self.produce_api()
        old_pass = Evidence(old_artifact, old_lease.input_signature, "tests-v1", "tester", True)
        self.kernel.verify("api", Evidence(old_artifact, old_lease.input_signature,
                                            "tests-v1", "tester", False))
        self.kernel.retry_rejected("api")
        lease = self.kernel.claim("api", "builder", now=2, ttl=10, max_credits=20)
        self.kernel.produce(lease, b"fixed", now=3, actual_credits=5)
        with self.assertRaises(Rejected):
            self.kernel.verify("api", old_pass)

    def test_repair_loop_exhausts_attempt_limit(self):
        for time in (0, 2):
            lease = self.kernel.claim("api", "builder", now=time, ttl=10, max_credits=10)
            artifact = self.kernel.produce(lease, b"bad", now=time + 1, actual_credits=4)
            self.kernel.verify("api", Evidence(artifact, lease.input_signature,
                                                "tests-v1", "tester", False))
            self.kernel.retry_rejected("api")
        self.assertEqual(self.kernel.snapshot("api")["state"], "EXHAUSTED")
        with self.assertRaises(Rejected):
            self.kernel.claim("api", "builder", now=5, ttl=10, max_credits=10)

    def test_unknown_dependencies_cannot_create_hidden_cycles(self):
        with self.assertRaises(Rejected):
            self.kernel.add_task("loop", {}, dependencies=("loop",))


class ExternalEffectFaultTests(unittest.TestCase):
    def setUp(self):
        self.ledger = EffectLedger()
        self.ledger.prepare("release:1", {"artifact": "sha256:one"},
                            receiver_deduplicates=False)

    def test_timeout_without_receiver_dedupe_blocks_retry(self):
        dispatch = self.ledger.begin("release:1")
        self.ledger.timeout(dispatch)
        with self.assertRaises(Rejected):
            self.ledger.begin("release:1")
        self.assertEqual(self.ledger.snapshot("release:1")["attempts"], 1)

    def test_string_false_cannot_enable_receiver_deduplication(self):
        with self.assertRaises(Rejected):
            self.ledger.prepare("unsafe", {}, receiver_deduplicates="false")

    def test_inconclusive_reconciliation_remains_blocked(self):
        dispatch = self.ledger.begin("release:1")
        self.ledger.timeout(dispatch)
        self.ledger.reconcile(dispatch, "UNKNOWN")
        with self.assertRaises(Rejected):
            self.ledger.begin("release:1")

    def test_confirmed_absence_allows_new_attempt(self):
        first = self.ledger.begin("release:1")
        self.ledger.timeout(first)
        self.ledger.reconcile(first, "NOT_APPLIED")
        second = self.ledger.begin("release:1")
        self.ledger.confirm(second)
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "APPLIED")

    def test_old_absence_report_cannot_clear_new_dispatch_uncertainty(self):
        first = self.ledger.begin("release:1")
        self.ledger.timeout(first)
        self.ledger.reconcile(first, "NOT_APPLIED")
        second = self.ledger.begin("release:1")
        self.ledger.timeout(second)
        with self.assertRaises(Rejected):
            self.ledger.reconcile(first, "NOT_APPLIED")
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "UNKNOWN")
        with self.assertRaises(Rejected):
            self.ledger.begin("release:1")
        self.assertEqual(self.ledger.snapshot("release:1")["attempts"], 2)

    def test_old_timeout_cannot_change_new_dispatch_state(self):
        first = self.ledger.begin("release:1")
        self.ledger.timeout(first)
        self.ledger.reconcile(first, "NOT_APPLIED")
        second = self.ledger.begin("release:1")
        with self.assertRaises(Rejected):
            self.ledger.timeout(first)
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "IN_FLIGHT")
        self.ledger.timeout(second)
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "UNKNOWN")

    def test_old_confirmation_cannot_resolve_new_dispatch(self):
        first = self.ledger.begin("release:1")
        self.ledger.timeout(first)
        self.ledger.reconcile(first, "NOT_APPLIED")
        second = self.ledger.begin("release:1")
        self.ledger.timeout(second)
        with self.assertRaises(Rejected):
            self.ledger.confirm(first)
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "UNKNOWN")
        self.ledger.confirm(second)
        self.assertEqual(self.ledger.snapshot("release:1")["state"], "APPLIED")

    def test_receiver_dedupe_allows_same_key_retry_after_timeout(self):
        self.ledger.prepare("safe:1", {"artifact": "same"}, receiver_deduplicates=True)
        first = self.ledger.begin("safe:1")
        self.ledger.timeout(first)
        second = self.ledger.begin("safe:1")
        self.ledger.confirm(second)
        self.assertEqual(self.ledger.snapshot("safe:1")["attempts"], 2)

    def test_idempotency_key_cannot_be_rebound_to_another_payload(self):
        with self.assertRaises(Rejected):
            self.ledger.prepare("release:1", {"artifact": "sha256:two"},
                                receiver_deduplicates=False)

    def test_recorded_success_prevents_duplicate_dispatch(self):
        dispatch = self.ledger.begin("release:1")
        self.ledger.confirm(dispatch)
        with self.assertRaises(Rejected):
            self.ledger.begin("release:1")


if __name__ == "__main__":
    unittest.main()
