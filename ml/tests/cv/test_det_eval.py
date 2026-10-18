import numpy as np
import pytest

from tastoria_ml.cv import det_eval as de


def test_iou_matrix():
    a = np.array([[0, 0, 10, 10]])
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]])
    assert np.allclose(de.iou_matrix(a, b), [[1.0, 50 / 150, 0.0]])


def _pred(dets):
    """dets: list of (img, cls, box, score)."""
    return {
        "img": np.array([d[0] for d in dets], int),
        "cls": np.array([d[1] for d in dets], int),
        "boxes": np.array([d[2] for d in dets], float).reshape(-1, 4),
        "scores": np.array([d[3] for d in dets], float),
    }


def test_perfect_detections_give_ap_one():
    gt = [(np.array([[0, 0, 10, 10], [20, 20, 40, 40]], float), np.array([0, 0]))]
    P = de.prepare(_pred([(0, 0, [0, 0, 10, 10], 0.9), (0, 0, [20, 20, 40, 40], 0.8)]), gt, 1)
    ap, _ = de.weighted_map(P)
    assert np.allclose(ap, 1.0)


def test_false_positive_ranked_first_matches_hand_computation():
    gt = [(np.array([[0, 0, 10, 10]], float), np.array([0]))]
    P = de.prepare(_pred([(0, 0, [50, 50, 60, 60], 0.9), (0, 0, [0, 0, 10, 10], 0.5)]), gt, 1)
    ap, _ = de.weighted_map(P)
    # recall reaches 1 at the 2nd det with precision 1/2; envelope = 0.5 at every recall threshold
    assert ap[0, 0] == pytest.approx(0.5)


def test_greedy_matching_one_gt_one_tp():
    gt = np.array([[0, 0, 10, 10]], float)
    det = np.array([[0, 0, 10, 10], [0, 0, 10, 9]], float)
    order, tp = de.match_greedy(det, np.array([0.6, 0.9]), gt)
    assert list(order) == [1, 0]
    assert tp[:, 0].tolist() == [True, False]  # the duplicate is an FP


def test_weights_equal_duplication():
    rng = np.random.default_rng(0)
    gts, dets = [], []
    for i in range(6):
        g = rng.uniform(0, 80, (3, 2))
        b = np.concatenate([g, g + rng.uniform(5, 20, (3, 2))], 1)
        gts.append((b, rng.integers(0, 2, 3)))
        for k in range(4):
            j = rng.integers(0, 3)
            dets.append((i, int(rng.integers(0, 2)), b[j] + rng.normal(0, 2, 4), float(rng.uniform())))
    P = de.prepare(_pred(dets), gts, 2)
    w = np.array([2, 1, 0, 1, 3, 1], float)
    ap_w, _ = de.weighted_map(P, w)
    # explicit duplication
    order = np.repeat(np.arange(6), w.astype(int))
    gts2 = [gts[i] for i in order]
    dets2 = [(new_i, c, b, s) for new_i, i in enumerate(order) for (ii, c, b, s) in dets if ii == i]
    ap_d, _ = de.weighted_map(de.prepare(_pred(dets2), gts2, 2))
    assert np.allclose(ap_w, ap_d, atol=1e-9)


def test_clusters_group_bangladesh_frames():
    files = np.array([
        "mendeley_bd__test__VID_20250228_124329_mp4-0010_jpg.rf.a.jpg",
        "mendeley_bd__test__VID_20250228_124329_mp4-0012_jpg.rf.b.jpg",
        "mendeley_bd__test__VID_20250228_124329_mp4-0025_jpg.rf.c.jpg",
        "openimages_v7__abc.jpg",
        "openimages_v7__def.jpg",
    ])
    cl = de.clusters(files)
    assert cl[0] == cl[1] and cl[1] != cl[2] and len(set(cl[3:])) == 2 and cl[3] not in cl[:3]


def test_paired_bootstrap_identical_arms_is_zero():
    gt = [(np.array([[0, 0, 10, 10]], float), np.array([0])) for _ in range(5)]
    P = de.prepare(_pred([(i, 0, [0, 0, 10, 10], 0.9) for i in range(5)]), gt, 1)
    r = de.paired_cluster_bootstrap([P], [P], np.arange(5), n_boot=50)
    assert r["map50_95"]["diff"] == 0 and r["map50_95"]["ci95"] == [0.0, 0.0]


@pytest.mark.parametrize("ci,verdict", [
    ([-0.01, 0.01], "equivalent"),
    ([0.02, 0.04], "different (outside margin)"),
    ([0.005, 0.03], "different from 0 but not shown beyond the margin"),
    ([-0.02, 0.01], "inconclusive"),
])
def test_equivalence(ci, verdict):
    assert de.equivalence(ci, 0.015) == verdict
