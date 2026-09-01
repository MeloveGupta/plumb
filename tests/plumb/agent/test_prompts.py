"""P3 step 5 -- the versioned system prompt and its hash (TRD §7.4)."""

from plumb.agent.prompts import _hash_dir, load_prompts


def test_system_prompt_states_the_five_commitments():
    text = load_prompts().system_text
    assert "Abstention is a valid, scored outcome" in text
    assert "fabricated resolution is worse than an escalation" in text
    assert "recorded data may be wrong" in text
    assert "Read and recommend only" in text
    assert "No unsourced numbers" in text


def test_prompt_hash_is_stable():
    assert load_prompts().sha256 == load_prompts().sha256
    assert len(load_prompts().sha256) == 64


def test_hash_is_content_sensitive(tmp_path):
    (tmp_path / "system.md").write_text("first wording")
    h1 = _hash_dir(tmp_path)
    (tmp_path / "system.md").write_text("second wording")
    h2 = _hash_dir(tmp_path)
    assert h1 != h2

    (tmp_path / "system.md").write_text("first wording")
    assert _hash_dir(tmp_path) == h1  # same bytes -> same digest


def test_hash_changes_when_a_prompt_file_is_added(tmp_path):
    (tmp_path / "system.md").write_text("system")
    before = _hash_dir(tmp_path)
    (tmp_path / "investigation.md").write_text("more")
    assert _hash_dir(tmp_path) != before
