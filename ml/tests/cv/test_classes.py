from tastoria_ml.cv.classes import load_classes, source_label_map, trained_classes, validate


def test_vision_class_table_is_consistent():
    classes = load_classes()
    assert 18 <= len(classes) <= 24
    assert validate(classes) == []


def test_every_class_has_reason_and_public_mapping_is_unique():
    classes = load_classes()
    oi = source_label_map(classes, "openimages_v7")
    bd = source_label_map(classes, "mendeley_bd")
    assert oi["Tomato"].id == "ca_chua" and bd["Tomato"].id == "ca_chua"
    assert bd["Cauliflower"].id == oi["Broccoli"].id == "sup_lo"
    # labels known to be the wrong concept must stay unmapped
    assert "Chicken" not in oi  # the live bird
    assert "Snake gourd" not in bd  # Trichosanthes, not luffa
    trained = trained_classes(classes, ("openimages_v7", "mendeley_bd"))
    assert {c.id for c in trained} >= {"ca_chua", "ca_rot", "trung", "tom", "nam"}
    assert "rau_muong" not in {c.id for c in trained}


def test_proposed_classes_are_consistent():
    import yaml

    from tastoria_ml.cv.build_yolo_v2 import all_class_rows
    from tastoria_ml.cv.classes import INGREDIENTS

    ing = {i["name_vi"]: i for i in yaml.safe_load(INGREDIENTS.read_text(encoding="utf-8"))["ingredients"]}
    recipe_ingredients = set()
    for f in (INGREDIENTS.parent / "recipes").rglob("*.yaml"):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        recipe_ingredients |= {ln.get("name") for ln in doc.get("ingredients") or [] if isinstance(ln, dict)}
    rows = all_class_rows()
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)
    for r in rows[len(load_classes()):]:
        assert r["instance_def"] in {"item", "group_of", "package"}
        assert not r["countable"] or r["instance_def"] == "item"
        for n in r["ingredients"]:
            assert n in ing, n
            # snacks are flagged non-meal and live in the do_an_vat food group (the backend hard filter always
            # excludes that group); a non-meal class outside do_an_vat (bánh mì, ngu_coc) must not be used by any
            # recipe, otherwise the composer could still put it on a tray
            if ing[n]["food_group"] == "do_an_vat":
                assert r["meal_ingredient"] is False, r["id"]
            elif r["meal_ingredient"] is False:
                assert n not in recipe_ingredients, (r["id"], n)
    for src in ("lvis_v1", "rpc_checkout", "omorros_kitchen"):
        labels = [x for r in rows for x in (r.get("public_data") or {}).get(src, [])]
        assert len(labels) == len(set(labels)), src


def test_deployed_detector_classes_are_in_the_table_and_match_the_docs():
    """The deployed ONNX (deploy/models/detector, not in git) outputs a subset of vision_classes.yaml; the docs
    (docs/reports/xu-ly-anh/bao-cao-xu-ly-anh.md, backend/README.md) state exactly these 13 classes."""
    import ast

    import pytest

    from tastoria_ml.cv.build_yolo_v2 import all_class_rows
    from tastoria_ml.cv.classes import REPO

    onnx_path = REPO / "deploy" / "models" / "detector" / "model.onnx"
    if not onnx_path.exists():
        pytest.skip("deployed detector not staged on this machine")
    ort = pytest.importorskip("onnxruntime")
    meta = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"]).get_modelmeta()
    names = ast.literal_eval(meta.custom_metadata_map["names"])
    assert sorted(names) == list(range(len(names)))
    assert set(names.values()) <= {r["id"] for r in all_class_rows()}
    assert list(names.values()) == ["ca", "tom", "trung", "ca_chua", "ca_rot", "khoai_tay", "bap_cai", "sup_lo",
                                    "bi_do", "bi_dao", "muop_dang", "dau_que", "nam"]
