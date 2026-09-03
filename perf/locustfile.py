"""
perf/locustfile.py
==================
Load profile for Hisaab, run against `perf.serve_fake`.

    make load                       # headless, 50 users, 60s
  or:
    .venv/bin/locust -f perf/locustfile.py --host http://127.0.0.1:8800

Each virtual user is a gig worker: opens a case, then a realistic mix of
viewing it, adding dates, chatting, adding proof, and drafting documents.
Traffic shows up in Jaeger (per-request traces) and Grafana (the
hisaab.* metrics) when `make otel-up` is running.
"""

import base64
import uuid

from locust import HttpUser, between, task

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 256).decode()


def _key():
    return {"Idempotency-Key": uuid.uuid4().hex}


class Worker(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        self.uid = "load-" + uuid.uuid4().hex[:10]
        self.h = {"Authorization": f"Bearer {self.uid}:token"}
        r = self.client.post("/api/cases", name="/api/cases [create]", json={
            "title": "Platform withheld my payment",
            "issue_type": "deactivation", "platform": "Uber",
            "incident_date": "2026-08-28", "amount_claimed_inr": 2400,
        }, headers={**self.h, **_key()})
        self.case = r.json().get("id") if r.status_code == 201 else None

    @task(6)
    def view_case(self):
        if self.case:
            self.client.get(f"/api/cases/{self.case}", name="/api/cases/{id}", headers=self.h)

    @task(3)
    def list_cases(self):
        self.client.get("/api/cases", headers=self.h)

    @task(4)
    def deadlines(self):
        if self.case:
            self.client.post(f"/api/cases/{self.case}/deadlines",
                             name="/api/cases/{id}/deadlines",
                             json={"notice_sent": "2026-09-01", "idrc_appeal_filed": "2026-09-02"},
                             headers=self.h)

    @task(3)
    def chat(self):
        if self.case:
            self.client.post(f"/api/cases/{self.case}/chat", name="/api/cases/{id}/chat",
                             json={"message": "what should I do next?"},
                             headers={**self.h, **_key()})

    @task(2)
    def evidence(self):
        if self.case:
            self.client.post(f"/api/cases/{self.case}/evidence", name="/api/cases/{id}/evidence",
                             json={"kind": "earnings_screen", "filename": "e.png",
                                   "mime": "image/png", "data_b64": _PNG},
                             headers={**self.h, **_key()})

    @task(2)
    def draft(self):
        if self.case:
            self.client.post(f"/api/cases/{self.case}/draft", name="/api/cases/{id}/draft",
                             json={"kind": "platform_grievance", "sender_name": "A. Kumar",
                                   "sender_worker_id": "W-1", "recipient_name": "Uber India"},
                             headers={**self.h, **_key()})

    @task(1)
    def appeal_record(self):
        if self.case:
            self.client.get(f"/api/cases/{self.case}/appeal-record",
                            name="/api/cases/{id}/appeal-record", headers=self.h)
