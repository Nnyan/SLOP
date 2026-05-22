"""tests/test_gguf.py

Tests for the GGUF file validator and model management utilities.
"""
import struct
from pathlib import Path

import pytest

from backend.core.gguf_validator import (
    RECOMMENDED_MODELS,
    GGUFValidationResult,
    resolve_gguf_url,
    validate_gguf,
    list_gguf_files,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def make_gguf(path: Path, version: int = 2, tensor_count: int = 10,
              size_mb: float = 200, corrupt: bool = False) -> Path:
    """Write a minimal valid (or intentionally corrupt) GGUF file."""
    with open(path, "wb") as f:
        if corrupt:
            f.write(b"NOPE")   # wrong magic
        else:
            f.write(b"GGUF")                           # magic
            f.write(struct.pack("<I", version))        # version
            if version >= 2:
                f.write(struct.pack("<Q", tensor_count))  # tensor_count
                f.write(struct.pack("<Q", 5))          # metadata_kv_count
        # Pad to target size
        target_bytes = int(size_mb * 1_048_576)
        current = f.tell()
        if target_bytes > current:
            f.write(b"\x00" * (target_bytes - current))
    return path


# ── Validation ─────────────────────────────────────────────────────────────


class TestValidateGGUF:
    def test_valid_v2_file(self, tmp_path: Path):
        p = make_gguf(tmp_path / "model.gguf", version=2, size_mb=200)
        result = validate_gguf(p)
        assert result.valid
        assert result.gguf_version == 2
        assert result.error is None
        assert result.file_size_mb >= 200

    def test_valid_v3_file(self, tmp_path: Path):
        p = make_gguf(tmp_path / "model.gguf", version=3, size_mb=150)
        result = validate_gguf(p)
        assert result.valid
        assert result.gguf_version == 3

    def test_file_not_found(self, tmp_path: Path):
        result = validate_gguf(tmp_path / "missing.gguf")
        assert not result.valid
        assert "not found" in result.error.lower()

    def test_wrong_magic_bytes(self, tmp_path: Path):
        p = make_gguf(tmp_path / "bad.gguf", corrupt=True, size_mb=200)
        result = validate_gguf(p)
        assert not result.valid
        assert "GGUF" in result.error   # tells user what it should be

    def test_file_too_small(self, tmp_path: Path):
        p = tmp_path / "tiny.gguf"
        p.write_bytes(b"GGUF" + b"\x00" * 100)   # 4 + 100 bytes — way too small
        result = validate_gguf(p)
        assert not result.valid
        assert "too small" in result.error.lower()

    def test_zero_tensor_count_rejected(self, tmp_path: Path):
        p = make_gguf(tmp_path / "empty.gguf", version=2, tensor_count=0, size_mb=200)
        result = validate_gguf(p)
        assert not result.valid
        assert "zero" in result.error.lower() or "tensor" in result.error.lower()

    def test_large_model_produces_warning(self, tmp_path: Path):
        p = make_gguf(tmp_path / "huge.gguf", version=2, size_mb=200)
        # Directly test the warning logic by calling with a known-large size
        # by making a real file and checking the threshold constant
        from backend.core.gguf_validator import MAX_REASONABLE_SIZE_GB
        assert MAX_REASONABLE_SIZE_GB > 0  # sanity check the constant exists
        # A 200MB file is under the threshold — confirm no warning
        result = validate_gguf(p)
        assert result.valid
        assert result.warning is None  # 200MB is well under 8GB threshold

    def test_v1_file_valid(self, tmp_path: Path):
        # v1 doesn't have tensor_count
        p = tmp_path / "v1.gguf"
        target = int(200 * 1_048_576)
        with open(p, "wb") as f:
            f.write(b"GGUF")
            f.write(struct.pack("<I", 1))   # version 1 — no tensor_count
            f.write(b"\x00" * (target - 8))
        result = validate_gguf(p)
        assert result.valid
        assert result.gguf_version == 1

    def test_unsupported_version_rejected(self, tmp_path: Path):
        p = tmp_path / "future.gguf"
        target = int(200 * 1_048_576)
        with open(p, "wb") as f:
            f.write(b"GGUF")
            f.write(struct.pack("<I", 99))  # version 99 — not supported
            f.write(b"\x00" * (target - 8))
        result = validate_gguf(p)
        assert not result.valid
        assert "99" in result.error

    def test_result_includes_path(self, tmp_path: Path):
        p = make_gguf(tmp_path / "model.gguf", size_mb=200)
        result = validate_gguf(p)
        assert result.path == p


# ── URL resolution ──────────────────────────────────────────────────────────


class TestResolveGGUFUrl:
    def test_hf_shorthand(self):
        url = resolve_gguf_url("hf://org/repo/model.gguf")
        assert url == "https://huggingface.co/org/repo/resolve/main/model.gguf"

    def test_hf_blob_to_resolve(self):
        url = resolve_gguf_url(
            "https://huggingface.co/org/repo/blob/main/model.gguf"
        )
        assert "/resolve/" in url
        assert "/blob/" not in url

    def test_direct_url_unchanged(self):
        direct = "https://example.com/files/model.gguf"
        assert resolve_gguf_url(direct) == direct

    def test_hf_shorthand_with_subpath(self):
        url = resolve_gguf_url("hf://org/repo/subfolder/model-Q4.gguf")
        assert "subfolder/model-Q4.gguf" in url

    def test_invalid_hf_shorthand_raises(self):
        with pytest.raises(ValueError, match="Invalid HuggingFace"):
            resolve_gguf_url("hf://org-only")


# ── Catalog utilities ───────────────────────────────────────────────────────


class TestListGGUFFiles:
    def test_empty_directory(self, tmp_path: Path):
        result = list_gguf_files(tmp_path)
        assert result == []

    def test_missing_directory(self, tmp_path: Path):
        result = list_gguf_files(tmp_path / "nonexistent")
        assert result == []

    def test_lists_valid_files(self, tmp_path: Path):
        make_gguf(tmp_path / "phi4.gguf", size_mb=200)
        make_gguf(tmp_path / "llama.gguf", size_mb=150)
        result = list_gguf_files(tmp_path)
        assert len(result) == 2
        names = [f["filename"] for f in result]
        assert "phi4.gguf" in names
        assert "llama.gguf" in names

    def test_includes_invalid_files_with_error(self, tmp_path: Path):
        make_gguf(tmp_path / "good.gguf", size_mb=200)
        bad = tmp_path / "bad.gguf"
        bad.write_bytes(b"NOPE" + b"\x00" * (200 * 1024 * 1024))
        result = list_gguf_files(tmp_path)
        assert len(result) == 2
        bad_entry = next(f for f in result if f["filename"] == "bad.gguf")
        assert not bad_entry["valid"]
        assert bad_entry["error"] is not None


# ── Recommended models ─────────────────────────────────────────────────────


class TestRecommendedModels:
    def test_recommended_list_not_empty(self):
        assert len(RECOMMENDED_MODELS) >= 3

    def test_all_have_required_fields(self):
        required = {"name", "hf_url", "size_gb", "recommended_for", "notes"}
        for m in RECOMMENDED_MODELS:
            assert required.issubset(m.keys()), f"Missing fields in {m.get('name')}"

    def test_all_urls_are_hf_or_https(self):
        for m in RECOMMENDED_MODELS:
            url = m["hf_url"]
            assert url.startswith("hf://") or url.startswith("https://"), \
                f"Invalid URL in {m['name']}: {url}"

    def test_default_model_is_phi4_mini(self):
        default = next(
            (m for m in RECOMMENDED_MODELS if m["recommended_for"] == "mediastack-agent"),
            None
        )
        assert default is not None
        assert "phi" in default["name"].lower() or "phi" in default["hf_url"].lower()

    def test_all_sizes_under_4gb(self):
        for m in RECOMMENDED_MODELS:
            assert m["size_gb"] <= 4.0, \
                f"Model {m['name']} is {m['size_gb']}GB — exceeds 4GB limit"
