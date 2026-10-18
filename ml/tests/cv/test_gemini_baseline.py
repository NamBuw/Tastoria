import json

import numpy as np
import pytest

from tastoria_ml.cv import gemini_baseline as gb

IDS = {"trung", "ca_chua", "ca", "thit_lon"}


def test_prompt_lists_all_22_classes_and_schema_enum():
    classes = gb.class_table()
    assert len(classes) == 22
    for v in ("v1", "v2"):
        p = gb.build_prompt(classes, v)
        assert all(f"- {c['id']}:" in p for c in classes)
        assert "box_2d" in p
    s = gb.response_schema([c["id"] for c in classes])
    assert s["items"]["properties"]["label"]["enum"] == [c["id"] for c in classes]


def test_parse_plain_json_and_box_order():
    txt = json.dumps([{"label": "trung", "box_2d": [100, 200, 300, 400]}])
    objs, rep = gb.parse_response(txt, IDS, width=1000, height=500)
    assert rep["n_raw"] == 1 and not rep["json_error"]
    # box_2d = [ymin, xmin, ymax, xmax] in 0..1000 -> xyxy pixels
    assert objs[0]["xyxy"] == pytest.approx([200, 50, 400, 150])


def test_parse_fenced_dict_wrapper_and_drops():
    txt = "```json\n" + json.dumps({"objects": [
        {"label": "ca_chua", "box_2d": [300, 400, 100, 200]},  # inverted -> sorted
        {"label": "banana", "box_2d": [0, 0, 10, 10]},  # unknown label
        {"label": "ca", "box_2d": [0, 0, 10]},  # bad box
        {"label": "ca", "box_2d": [5, 5, 5, 9]},  # zero height
        {"label": "ca", "box_2d": [-50, 0, 1200, 500]},  # clipped
    ]}) + "\n```"
    objs, rep = gb.parse_response(txt, IDS, 1000, 1000)
    assert [o["label"] for o in objs] == ["ca_chua", "ca"]
    assert objs[0]["xyxy"] == pytest.approx([200, 100, 400, 300])
    assert objs[1]["xyxy"] == pytest.approx([0, 0, 500, 1000])
    assert rep["unknown_label"] == 1 and rep["bad_box"] == 2


def test_parse_garbage_and_salvage():
    objs, rep = gb.parse_response("sorry, I can't", IDS, 10, 10)
    assert objs == [] and rep["json_error"]
    objs, rep = gb.parse_response('Here: [{"label": "trung", "box_2d": [0,0,500,500]}] done', IDS, 10, 10)
    assert len(objs) == 1 and not rep["json_error"]
    assert gb.parse_response("", IDS, 10, 10)[0] == []


def test_hungarian_one_to_one():
    gt = np.array([[0, 0, 10, 10], [20, 0, 30, 10]], float)
    pred = np.array([[0, 0, 10, 10], [1, 0, 11, 10], [20, 0, 30, 10]], float)
    assert gb.match_hungarian(pred, gt, 0.5) == 2
    assert gb.match_hungarian(pred[:1], gt, 0.5) == 1
    assert gb.match_hungarian(np.zeros((0, 4)), gt, 0.5) == 0


def test_evaluate_records_on_mocked_run():
    gt = {
        "a.jpg": [{"label": "trung", "xyxy": [0, 0, 10, 10]}, {"label": "trung", "xyxy": [20, 0, 30, 10]},
                  {"label": "ca", "xyxy": [0, 20, 40, 60]}],
        "b.jpg": [{"label": "ca_chua", "xyxy": [0, 0, 50, 50]}],
    }
    recs = [
        {"file": "a.jpg", "latency_s": 1.0, "usage": {"prompt_tokens": 1000, "output_tokens": 100},
         "objects": [{"label": "trung", "xyxy": [0, 0, 10, 10]}, {"label": "trung", "xyxy": [21, 0, 31, 10]},
                     {"label": "thit_lon", "xyxy": [0, 0, 5, 5]}]},
        {"file": "b.jpg", "latency_s": 3.0, "usage": {"prompt_tokens": 1000, "output_tokens": 50},
         "objects": [{"label": "ca_chua", "xyxy": [0, 0, 30, 30]}]},  # IoU 0.36: hit only at 0.3
    ]
    r = gb.evaluate_records(recs, gt, ["ca", "trung", "ca_chua"], {"trung", "ca_chua"}, price_in=0.3,
                            price_out=2.5)
    assert r["box_iou0.5"]["tp"] == 2 and r["box_iou0.5"]["n_pred"] == 3 and r["box_iou0.5"]["n_gt"] == 4
    assert r["box_iou0.3"]["tp"] == 3
    assert r["list_level"]["precision"] == pytest.approx(1.0)
    assert r["list_level"]["recall"] == pytest.approx(2 / 3)
    assert r["counting"]["mae"] == 0 and r["counting"]["n_pairs"] == 2
    assert r["out_of_dataset_objects"] == 1
    assert r["latency_s"]["p50"] == pytest.approx(2.0)
    assert r["cost_usd"]["total"] == pytest.approx(2000 / 1e6 * 0.3 + 150 / 1e6 * 2.5)


def test_run_with_fake_caller_is_resumable(tmp_path, monkeypatch):
    img_dir = tmp_path / "images" / "val"
    img_dir.mkdir(parents=True)
    for n in ("x.jpg", "y.jpg"):
        (img_dir / n).write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(gb, "YOLO_DIR", tmp_path)
    monkeypatch.setattr(gb, "RAW", tmp_path / "raw")
    calls = []

    def fake(client, model, data, prompt, schema):
        calls.append(model)
        return '[{"label": "trung", "box_2d": [0, 0, 100, 100]}]', {"prompt_tokens": 10, "output_tokens": 5}, 0.1

    out = gb.run("val", "v1", "gemini-test", client=object(), caller=fake)
    gb.run("val", "v1", "gemini-test", client=object(), caller=fake)  # second call: nothing new
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(lines) == 2 and len(calls) == 2
    assert lines[0]["model"] == "gemini-test" and lines[0]["prompt"] == "v1"
