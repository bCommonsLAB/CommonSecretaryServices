from src.utils.xxl_chunk_sizing import XXLChunkSizingConfig, compute_xxl_chunk_sizing


def test_compute_xxl_chunk_sizing_basic() -> None:
    cfg = XXLChunkSizingConfig(
        context_length_tokens=1_000_000,
        prompt_token_reserve=10_000,
        response_token_reserve=10_000,
        overlap_ratio=0.04,
        chars_per_token=2.5,
        min_chunk_chars=20_000,
        max_chunk_chars=2_000_000,
    )
    res = compute_xxl_chunk_sizing(cfg)

    assert res.available_input_tokens == 980_000
    assert res.chunk_size_chars > 0
    assert 0 <= res.overlap_chars < res.chunk_size_chars
    # 4% overlap (gerundet)
    assert abs(res.overlap_chars - int(round(res.chunk_size_chars * 0.04))) <= 1


def test_compute_xxl_chunk_sizing_guardrails() -> None:
    # Chunk wäre riesig, wird aber auf max_chunk_chars geklemmt
    cfg = XXLChunkSizingConfig(
        context_length_tokens=2_000_000,
        prompt_token_reserve=1,
        response_token_reserve=1,
        overlap_ratio=0.04,
        chars_per_token=10.0,
        min_chunk_chars=20_000,
        max_chunk_chars=100_000,
    )
    res = compute_xxl_chunk_sizing(cfg)
    assert res.chunk_size_chars == 100_000
    assert 0 <= res.overlap_chars < 100_000






