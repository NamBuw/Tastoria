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
