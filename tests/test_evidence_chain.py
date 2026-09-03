from app.core import evidence_chain as ec


def _entry(seq, prev, sha, kind="payslip", ts="2026-09-01T00:00:00+00:00", fn="f.png"):
    return {"seq": seq, "prev_hash": prev,
            "chain_hash": ec.chain_hash(prev, sha, ts, kind),
            "sha256": sha, "captured_at": ts, "kind": kind, "filename": fn}


def _build(n):
    entries = []
    prev = ec.GENESIS
    for i in range(1, n + 1):
        sha = ec.sha256_hex(f"file{i}".encode())
        link = ec.link(entries[-1] if entries else None,
                       file_sha256=sha, captured_at=f"2026-09-0{i}T00:00:00+00:00",
                       kind="payslip")
        entries.append({**link, "sha256": sha,
                        "captured_at": f"2026-09-0{i}T00:00:00+00:00",
                        "kind": "payslip", "filename": f"f{i}.png"})
        prev = link["chain_hash"]
    return entries


def test_link_starts_at_genesis():
    first = ec.link(None, file_sha256="abc", captured_at="t", kind="payslip")
    assert first["seq"] == 1 and first["prev_hash"] == ec.GENESIS


def test_valid_chain_verifies():
    r = ec.verify(_build(4))
    assert r["ok"] is True and r["length"] == 4 and r["broken_at"] is None


def test_tampered_bytes_break_the_chain():
    entries = _build(3)
    entries[1]["sha256"] = ec.sha256_hex(b"swapped file")  # edit a stored file hash
    r = ec.verify(entries)
    assert r["ok"] is False and r["broken_at"] == 2


def test_reordering_breaks_the_chain():
    entries = _build(3)
    entries[1], entries[2] = entries[2], entries[1]
    entries[1]["seq"], entries[2]["seq"] = 2, 3
    assert ec.verify(entries)["ok"] is False


def test_deleting_an_entry_breaks_the_chain():
    entries = _build(4)
    del entries[2]
    assert ec.verify(entries)["ok"] is False


def test_manifest_signed_and_unsigned():
    entries = _build(2)
    signed = ec.manifest(entries, signing_key="topsecret")
    assert signed["signature"]["alg"] == "HMAC-SHA256"
    assert signed["head"] == entries[-1]["chain_hash"]
    assert signed["verification"]["ok"] is True
    assert "data_b64" not in signed["entries"][0]

    unsigned = ec.manifest(entries, signing_key=None)
    assert unsigned["signature"] is None

    # signature is deterministic and key-dependent
    assert ec.manifest(entries, signing_key="topsecret")["signature"]["value"] \
        == signed["signature"]["value"]
    assert ec.manifest(entries, signing_key="other")["signature"]["value"] \
        != signed["signature"]["value"]
