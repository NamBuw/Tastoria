"""UC28: `tastoria mlops export-training-data` — consent gating, deletion exclusion, HMAC aliasing, SHA-256."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from helpers import bearer, register
from kb_helpers import API, grant, q, recipe_id
from PIL import Image

from tastoria.cli import main
from tastoria.core.config import get_settings


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def test_mlops_export_training_data_end_to_end(
    kb_client: TestClient, kb_db, kb_database_url: str, storage_dir: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    u_ok = register(kb_client)
    u_withdrawn = register(kb_client)
    u_del_req = register(kb_client)
    u_no_consent = register(kb_client)

    uid_ok = u_ok["user"]["id"]
    uid_w = u_withdrawn["user"]["id"]
    uid_del = u_del_req["user"]["id"]
    uid_nc = u_no_consent["user"]["id"]

    h_ok = bearer(u_ok)
    h_w = bearer(u_withdrawn)
    h_del = bearer(u_del_req)
    grant(kb_client, h_ok, "personalization")
    grant(kb_client, h_ok, "photo_contribution")
    grant(kb_client, h_w, "personalization")
    grant(kb_client, h_w, "photo_contribution")
    grant(kb_client, h_del, "personalization")

    rid = recipe_id(kb_db, "Ba chỉ chiên nước mắm")
    now = datetime.now(UTC)
    for hdr in (h_ok, h_w, h_del):
        kb_client.post(
            f"{API}/events",
            json={"events": [{"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": rid, "occurred_at": now.isoformat()}]},
            headers=hdr,
        )
    # Mark u_del_req as deletion_requested
    q(kb_db, "UPDATE users SET status = 'deletion_requested' WHERE id = :u", u=uid_del)
    # Withdraw u_withdrawn's personalization consent -> interactions erased & revocation recorded
    kb_client.post(f"{API}/me/consents/personalization/withdraw", json={"channel": "settings"}, headers=h_w)

    # Create scans for u_ok (1 contributed active, 1 not contributed, 1 purged contributed)
    ing_id = str(q(kb_db, "SELECT id FROM ingredients WHERE is_active LIMIT 1").scalar())
    vcls_id = int(q(kb_db, "SELECT id FROM vision_classes ORDER BY id LIMIT 1").scalar())
    scan_ok = str(uuid.uuid4())
    scan_nc = str(uuid.uuid4())
    img_ok_id = str(uuid.uuid4())
    img_purged_id = str(uuid.uuid4())
    img_nc_id = str(uuid.uuid4())
    item_edit_id = str(uuid.uuid4())
    item_kept_id = str(uuid.uuid4())

    key_ok = f"contrib/{uid_ok}/{scan_ok}/1.jpg"
    (storage_dir / key_ok).parent.mkdir(parents=True, exist_ok=True)
    (storage_dir / key_ok).write_bytes(_jpeg_bytes())

    q(
        kb_db,
        "INSERT INTO scans (id, user_id, mode, status, confirmed_at, created_at) "
        "VALUES (:s, :u, 'fridge', 'confirmed', :t, :t)",
        s=scan_ok,
        u=uid_ok,
        t=now,
    )
    q(
        kb_db,
        "INSERT INTO scan_images (id, scan_id, ordinal, shelf_group, storage_key, width, height, contributed, purged_at) "
        "VALUES (:id, :s, 1, 1, :k, 64, 64, true, NULL)",
        id=img_ok_id,
        s=scan_ok,
        k=key_ok,
    )
    q(
        kb_db,
        "INSERT INTO scan_images (id, scan_id, ordinal, shelf_group, storage_key, width, height, contributed, purged_at) "
        "VALUES (:id, :s, 2, 1, :k, 64, 64, true, :t)",
        id=img_purged_id,
        s=scan_ok,
        k=f"contrib/{uid_ok}/{scan_ok}/2.jpg",
        t=now,
    )
    q(
        kb_db,
        "INSERT INTO scan_items (id, scan_id, ingredient_id, origin, model_count, final_count, user_action, created_at, updated_at) "
        "VALUES (:id, :s, :ing, 'model', 2, 3, 'edited', :t, :t)",
        id=item_edit_id,
        s=scan_ok,
        ing=ing_id,
        t=now,
    )
    q(
        kb_db,
        "INSERT INTO scan_items (id, scan_id, ingredient_id, origin, model_count, final_count, user_action, created_at, updated_at) "
        "VALUES (:id, :s, :ing, 'model', 1, 1, 'kept', :t, :t)",
        id=item_kept_id,
        s=scan_ok,
        ing=ing_id,
        t=now,
    )
    q(
        kb_db,
        "INSERT INTO detections (scan_image_id, scan_item_id, vision_class_id, x1, y1, x2, y2, confidence, "
        "p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) "
        "VALUES (:im, :it, :vc, 0.1, 0.1, 0.5, 0.5, 0.9, 0.8, 0.1, 0.1, 0.0)",
        im=img_ok_id,
        it=item_edit_id,
        vc=vcls_id,
    )
    q(
        kb_db,
        "INSERT INTO scans (id, user_id, mode, status, created_at) VALUES (:s, :u, 'haul', 'done', :t)",
        s=scan_nc,
        u=uid_nc,
        t=now,
    )
    q(
        kb_db,
        "INSERT INTO scan_images (id, scan_id, ordinal, shelf_group, storage_key, width, height, contributed, purged_at) "
        "VALUES (:id, :s, 1, 1, :k, 64, 64, false, NULL)",
        id=img_nc_id,
        s=scan_nc,
        k=f"tmp/scans/{uid_nc}/{scan_nc}/1.jpg",
    )

    hmac_secret = "unit-test-export-hmac-secret-key"
    out_dir = tmp_path / "exports"
    monkeypatch.setenv("TASTORIA_DATABASE_URL", kb_database_url)
    monkeypatch.setenv("TASTORIA_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("TASTORIA_TRAINING_EXPORT_HMAC_KEY", hmac_secret)
    monkeypatch.setenv("TASTORIA_TRAINING_EXPORT_HMAC_KEY_ID", "exp-k1")
    get_settings.cache_clear()
    try:
        since_vn = (now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date() - timedelta(days=1)).isoformat()
        rc = main(["mlops", "export-training-data", "--since", since_vn, "--out", str(out_dir)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        exp_path = Path(payload["directory"])
        manifest = json.loads((exp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["hmac_key_id"] == "exp-k1"

        # Verify SHA-256 of every listed file
        for rel, meta in manifest["files"].items():
            f = exp_path / rel
            assert f.is_file()
            assert hashlib.sha256(f.read_bytes()).hexdigest() == meta["sha256"]

        # Verify ZERO raw user IDs, emails, or raw contrib storage_keys anywhere in exported text files
        all_text = "\n".join(p.read_text(encoding="utf-8") for p in exp_path.glob("*") if p.is_file())
        for forbidden_str in (uid_ok, uid_w, uid_del, uid_nc, u_ok["user"]["email"], "contrib/"):
            assert forbidden_str not in all_text

        ok_alias = hmac.new(hmac_secret.encode(), uuid.UUID(uid_ok).bytes, hashlib.sha256).hexdigest()
        w_alias = hmac.new(hmac_secret.encode(), uuid.UUID(uid_w).bytes, hashlib.sha256).hexdigest()

        interactions = list(csv.DictReader((exp_path / "interactions.csv").open(encoding="utf-8")))
        assert len(interactions) == 1
        assert interactions[0]["user_alias"] == ok_alias
        assert interactions[0]["occurred_date"] == now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()

        images = list(csv.DictReader((exp_path / "contributed_images.csv").open(encoding="utf-8")))
        assert len(images) == 1
        assert images[0]["user_alias"] == ok_alias
        assert images[0]["image_path"].startswith("images/") and (exp_path / images[0]["image_path"]).is_file()

        items = list(csv.DictReader((exp_path / "scan_items.csv").open(encoding="utf-8")))
        assert len(items) == 1 and items[0]["user_action"] == "edited"  # 'kept' excluded

        revs = list(csv.DictReader((exp_path / "revoked_aliases.csv").open(encoding="utf-8")))
        assert any(r["user_alias"] == w_alias and r["reason"] == "withdraw" for r in revs)

        # Validation failures: future date & hmac-key-file inside --out
        future = (date.today() + timedelta(days=5)).isoformat()
        assert main(["mlops", "export-training-data", "--since", future, "--out", str(out_dir)]) == 1
        capsys.readouterr()

        bad_key_file = out_dir / "secret.key"
        bad_key_file.write_text("abc", encoding="utf-8")
        assert (
            main(
                [
                    "mlops",
                    "export-training-data",
                    "--since",
                    since_vn,
                    "--out",
                    str(out_dir),
                    "--hmac-key-file",
                    str(bad_key_file),
                ]
            )
            == 1
        )
        capsys.readouterr()

        audits = list(
            q(kb_db, "SELECT purpose FROM audit_log WHERE action = 'training_export' ORDER BY id").scalars()
        )
        assert len(audits) == 3
        assert audits[0].startswith("ok:")
        assert audits[1].startswith("failed: future_since")
        assert audits[2].startswith("failed: hmac_key_inside_out")
    finally:
        get_settings.cache_clear()
