import pytest

from tastoria_ml.cv.freshness import MANIFEST, load_table


@pytest.mark.skipif(not MANIFEST.exists(), reason="freshness manifest not built")
def test_table_drops_augmented_and_conflicts_and_builds_lots():
    df = load_table()
    assert (df.is_augmented.astype(str) == "False").all()
    assert (df.label_conflict.astype(str) == "False").all()
    assert set(df.y) == {0, 1, 2}
    agri = df[df.dataset == "agrifreshnet"]
    dated = agri[agri.lot.str.match(r"agrifreshnet/[a-z]+/20\d{6}$")]
    # most AgriFreshNET originals carry a capture date in the file name -> session lots
    assert len(dated) / len(agri) > 0.95
    # a lot never mixes produce
    assert (dated.groupby("lot").produce.nunique() == 1).all()
    # spinach has no published lot: one group per image
    sp = df[df.dataset == "local_spinach_leaf"]
    assert sp.lot.nunique() == len(sp)
