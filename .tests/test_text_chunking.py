from src.utils.text_chunking import chunk_text_by_chars


def test_chunk_text_by_chars_overlap_and_offsets() -> None:
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26 chars
    chunks = chunk_text_by_chars(text=text, chunk_size_chars=10, overlap_chars=2)

    # Erwartete Slices: [0:10], [8:18], [16:26]
    assert len(chunks) == 3
    assert (chunks[0].start, chunks[0].end, chunks[0].text) == (0, 10, text[0:10])
    assert (chunks[1].start, chunks[1].end, chunks[1].text) == (8, 18, text[8:18])
    assert (chunks[2].start, chunks[2].end, chunks[2].text) == (16, 26, text[16:26])

    # Overlap prüfen: Ende von Chunk0 überlappt Anfang von Chunk1 um 2 Zeichen
    assert chunks[0].text[-2:] == chunks[1].text[:2]


def test_chunk_text_by_chars_empty_returns_empty_list() -> None:
    assert chunk_text_by_chars(text="", chunk_size_chars=10, overlap_chars=0) == []






