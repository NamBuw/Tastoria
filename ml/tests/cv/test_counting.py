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
