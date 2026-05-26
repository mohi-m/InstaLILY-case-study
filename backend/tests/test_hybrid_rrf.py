from app.search.hybrid import _rrf_fuse


def test_rrf_rewards_agreement():
    # 7 appears in both lists -> should outrank items in only one list.
    fts = [1, 2, 7]
    vec = [3, 4, 7]
    fused = _rrf_fuse(fts, vec)
    assert fused[0] == 7


def test_rrf_preserves_all_ids():
    fused = _rrf_fuse([1, 2], [2, 3])
    assert set(fused) == {1, 2, 3}


def test_rrf_top_rank_beats_lower():
    # Same single list -> order preserved.
    assert _rrf_fuse([10, 20, 30], []) == [10, 20, 30]
