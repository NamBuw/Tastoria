import numpy as np
import pytest

from tastoria_ml.cv import counting as ct


def test_count_metrics_ignores_pairs_absent_on_both_sides():
    c = np.array([0, 3, 2, 0, 1])
    chat = np.array([0, 3, 4, 1, 0])
    m = ct.count_metrics(c, chat)
    assert m["n_pairs"] == 4  # the (0, 0) pair is not a pair
    assert m["mae"] == pytest.approx((0 + 2 + 1 + 1) / 4)
    assert m["rel_mae"] == pytest.approx(4 / 6)
    assert m["exact"] == pytest.approx(1 / 4)
    assert m["within1"] == pytest.approx(3 / 4)


def test_empty():
    assert ct.count_metrics(np.zeros(3), np.zeros(3))["n_pairs"] == 0


def test_pred_counts_and_conf_choice():
    pred = {"img": np.array([0, 0, 0, 1]), "cls": np.array([0, 0, 1, 0]),
            "scores": np.array([0.9, 0.3, 0.8, 0.6])}
    c = np.array([[1, 1], [1, 0]])
    assert ct.pred_counts(pred, 2, 2, 0.5).tolist() == [[1, 1], [1, 0]]
    assert ct.pred_counts(pred, 2, 2, 0.2).tolist() == [[2, 1], [1, 0]]
    conf, curve = ct.choose_conf(c, pred, [0, 1])
    assert curve[0][1] > 0 and 0.3 < conf < 0.6 + 1e-9


def test_excluded_pairs_are_dropped():
    c = np.array([[5], [2]])
    chat = np.array([[1], [2]])
    exc = np.array([[True], [False]])
    m = ct.masked_metrics(c, chat, exc, [0])
    assert m["n_pairs"] == 1 and m["mae"] == 0


def test_group_of_pairs_heldout_returns_all_false():
    files = np.array(["lvis_v1__val__100604.jpg", "rpc_checkout__20180824.jpg", "omorros_kitchen__IMG_001.jpg"])
    names = ["thit_bo", "ca", "ca_chua"]
    out = ct.group_of_pairs("heldout", files, names)
    assert out.shape == (3, 3)
    assert out.dtype == bool
    assert not out.any()


def test_countable_ids_includes_proposed_when_requested():
    main_c = ct.countable_ids(include_proposed=False)
    all_c = ct.countable_ids(include_proposed=True)
    assert "trung" in main_c
    assert "mi_tom" not in main_c
    assert {"mi_tom", "do_hop", "sua", "chanh", "nuoc_ngot"} <= all_c
    assert len(all_c) > len(main_c)


def test_per_pair_errors_aligns_arrays_and_clusters():
    c = np.array([[2, 0], [0, 1], [3, 0]])
    chat_a = np.array([[2, 1], [0, 0], [1, 0]])
    chat_b = np.array([[0, 0], [0, 0], [0, 0]])
    exc = np.array([[False, False], [True, False], [False, False]])
    files = np.array([
        "mendeley_bd__test__VID_20250228_124329_mp4-0001_jpg.rf.a.jpg",
        "mendeley_bd__test__VID_20250228_124329_mp4-0002_jpg.rf.b.jpg",
        "openimages_v7__test__001.jpg",
    ])
    # Union mask where either GT > 0 or model A pred > 0
    mask = (c > 0) | (chat_a > 0)
    ea = ct.per_pair_errors(c, chat_a, exc, [0, 1], files=files, mask=mask)
    eb = ct.per_pair_errors(c, chat_b, exc, [0, 1], files=files, mask=mask)
    assert ea["abs_err"].shape == eb["abs_err"].shape == (4,)
    assert ea["abs_err"].tolist() == [0.0, 1.0, 1.0, 2.0]
    assert eb["abs_err"].tolist() == [2.0, 0.0, 1.0, 3.0]
    assert ea["exact"].tolist() == [True, False, False, False]
    assert ea["cluster_ids"][0] == ea["cluster_ids"][2]  # same BD frame block
    assert ea["cluster_ids"][3] != ea["cluster_ids"][0]
