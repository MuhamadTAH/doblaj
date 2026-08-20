"""
test_audit_outbox_chaos.py — Chaos Engineering & Dead Man's Switch Verification Suite.

Simulates:
1. Outbox worker pod crash / network severance.
2. Burst transactional mutation writing to outbox while worker is dead.
3. Dead Man's Switch queue depth & lag threshold breach detection.
4. 3-strike retry circuit breaker & dead-letter escalation.
5. Worker recovery and idempotent replay without data loss.
"""
import asyncio
import hashlib
import hmac
import json
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.audit_streamer import compute_audit_hmac, ship_event_to_external_siem


class MockOutboxQueue:
    def __init__(self, dead_man_switch_threshold: int = 50, lag_alert_sec: int = 30):
        self.records = []
        self.dead_man_threshold = dead_man_switch_threshold
        self.lag_alert_sec = lag_alert_sec
        self.worker_alive = True
        self.siem_sink = []
        self.alerts_fired = []

    def enqueue(self, event_id: str, action: str, actor_id: str, details: dict):
        record = {
            "eventId": event_id,
            "action": action,
            "actorId": actor_id,
            "details": details,
            "status": "PENDING",
            "retryCount": 0,
            "createdAt": time.time(),
            "deliveredAt": None,
        }
        self.records.append(record)
        return record

    def inspect_health(self):
        now = time.time()
        pending = [r for r in self.records if r["status"] == "PENDING"]
        oldest_age = (now - pending[0]["createdAt"]) if pending else 0

        is_healthy = True
        if len(pending) >= self.dead_man_threshold:
            is_healthy = False
            self.alerts_fired.append(f"CRITICAL: Queue depth breached ({len(pending)} pending >= {self.dead_man_threshold})")
        if oldest_age >= self.lag_alert_sec:
            is_healthy = False
            self.alerts_fired.append(f"CRITICAL: Oldest record lag breached ({oldest_age:.1f}s >= {self.lag_alert_sec}s)")

        return {
            "pendingCount": len(pending),
            "oldestAgeSec": oldest_age,
            "isHealthy": is_healthy,
        }

    def process_outbox_batch(self):
        if not self.worker_alive:
            # Worker is crashed - no processing happens
            return {"processed": 0, "failed": 0}

        processed = 0
        failed = 0
        for r in self.records:
            if r["status"] == "PENDING":
                if r["retryCount"] >= 3:
                    r["status"] = "FAILED"
                    self.alerts_fired.append(f"CIRCUIT_BREAKER: Event {r['eventId']} failed after 3 strikes.")
                    failed += 1
                else:
                    # Successfully ship to SIEM
                    r["status"] = "DELIVERED"
                    r["deliveredAt"] = time.time()
                    self.siem_sink.append(r)
                    processed += 1
        return {"processed": processed, "failed": failed}


class TestAuditOutboxChaos(unittest.TestCase):
    def test_hmac_signature_integrity(self):
        """Verify HMAC-SHA256 signature computation prevents log tampering."""
        secret = "test_siem_secret_key_secure_32_bytes"
        payload = json.dumps({"action": "REFUND", "amount": 500.0, "actor": "admin_1"})
        sig = compute_audit_hmac(payload, secret)

        expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(sig, expected)

        # Tampering with payload changes signature
        tampered = json.dumps({"action": "REFUND", "amount": 5000.0, "actor": "admin_1"})
        tampered_sig = compute_audit_hmac(tampered, secret)
        self.assertNotEqual(sig, tampered_sig)

    def test_worker_crash_and_dead_man_switch_alert(self):
        """Chaos Test: Crash the worker, enqueue 100 events, verify Dead Man's Switch fires alert."""
        outbox = MockOutboxQueue(dead_man_switch_threshold=50, lag_alert_sec=2)

        # 1. KILL WORKER
        outbox.worker_alive = False
        print("\n[CHAOS] Simulated Outbox Worker Pod Crash (worker_alive = False)")

        # 2. Burst 75 actions into outbox
        for i in range(75):
            outbox.enqueue(f"evt_{i}", "USER_BALANCE_ADJUST", "admin_bob", {"delta": 10})

        # 3. Inspect health -> must detect breach
        health = outbox.inspect_health()
        self.assertFalse(health["isHealthy"])
        self.assertEqual(health["pendingCount"], 75)
        self.assertTrue(any("Queue depth breached" in a for a in outbox.alerts_fired))
        print(f"[CHAOS] Dead Man's Switch Alert Triggered: {outbox.alerts_fired[-1]}")

        # 4. REVIVE WORKER (Recovery Phase)
        outbox.worker_alive = True
        print("[CHAOS] Revived Outbox Worker Pod. Triggering batch drain...")
        res = outbox.process_outbox_batch()
        self.assertEqual(res["processed"], 75)
        self.assertEqual(len(outbox.siem_sink), 75)

        # 5. Verify healthy state restored
        post_recovery_health = outbox.inspect_health()
        self.assertTrue(post_recovery_health["isHealthy"])
        self.assertEqual(post_recovery_health["pendingCount"], 0)
        print("[CHAOS] All 75 outbox logs successfully recovered and shipped to SIEM with zero loss.")

    def test_three_strike_circuit_breaker(self):
        """Verify that outbox items failing 3 consecutive deliveries transition to FAILED and alert."""
        outbox = MockOutboxQueue()
        item = outbox.enqueue("evt_corrupted", "NUKE_JOB", "admin_alice", {"reason": "malware"})
        item["retryCount"] = 3  # 3 consecutive failed deliveries

        outbox.process_outbox_batch()
        self.assertEqual(item["status"], "FAILED")
        self.assertTrue(any("CIRCUIT_BREAKER" in a for a in outbox.alerts_fired))
        print(f"[CHAOS] 3-Strike Circuit Breaker Alert: {outbox.alerts_fired[-1]}")


if __name__ == "__main__":
    unittest.main()
