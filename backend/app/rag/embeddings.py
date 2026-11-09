"""Pinned, CPU-only real embeddings. Runtime never downloads model assets."""

import argparse
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DIMENSIONS = 384
DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[3] / ".cache" / "embeddings" / MODEL_REVISION
)
FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "model.safetensors",
    "1_Pooling/config.json",
]


class EmbeddingUnavailable(RuntimeError):
    pass


def model_path() -> Path:
    return Path(os.environ.get("EMBEDDING_MODEL_PATH", str(DEFAULT_MODEL_PATH)))


def verify_assets(path: Path) -> None:
    try:
        manifest = json.loads((path / "asset_manifest.json").read_text())
        if manifest["model"] != MODEL_ID or manifest["revision"] != MODEL_REVISION:
            raise ValueError("Unexpected embedding identity")
        if set(manifest["files"]) != set(FILES):
            raise ValueError("Incomplete embedding cache")
        for filename in FILES:
            if (
                hashlib.sha256((path / filename).read_bytes()).hexdigest()
                != manifest["files"][filename]
            ):
                raise ValueError("Embedding asset checksum mismatch")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EmbeddingUnavailable(
            "Pinned embedding assets unavailable; run "
            "python -m app.rag.embeddings --download"
        ) from error


def download_assets(path: Path) -> None:
    from huggingface_hub import snapshot_download

    path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=path,
        allow_patterns=FILES,
        token=False,
    )
    manifest = {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "files": {
            filename: hashlib.sha256((path / filename).read_bytes()).hexdigest()
            for filename in FILES
        },
    }
    (path / "asset_manifest.json").write_text(json.dumps(manifest, indent=2))
    verify_assets(path)


class LocalEmbeddings:
    model_id = MODEL_ID
    revision = MODEL_REVISION

    def __init__(self, path: Path | None = None):
        path = path or model_path()
        verify_assets(path)

        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(2)
        torch.manual_seed(0)
        self.model = SentenceTransformer(
            str(path),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            token=False,
            model_kwargs={"use_safetensors": True},
        )
        if self.model.get_sentence_embedding_dimension() != DIMENSIONS:
            raise EmbeddingUnavailable("Unexpected embedding dimensions")
        self.tokenizer = self.model.tokenizer
        self.max_tokens = min(self.model.max_seq_length, 256) - 2

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        for text in texts:
            if (
                not text.strip()
                or len(self.tokenizer.encode(text, add_special_tokens=False))
                > self.max_tokens
            ):
                raise ValueError("Embedding input is empty or exceeds the token budget")
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if vectors.shape != (len(texts), DIMENSIONS) or not np.isfinite(vectors).all():
            raise EmbeddingUnavailable("Invalid local embedding output")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
            raise EmbeddingUnavailable("Embeddings must be normalized")
        return vectors.astype(np.float32).tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> LocalEmbeddings:
    return LocalEmbeddings()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        download_assets(model_path())
    embedder = get_embeddings()
    vector = embedder.encode(["Local embedding verification"])[0]
    print(
        json.dumps(
            {
                "model": MODEL_ID,
                "revision": MODEL_REVISION,
                "dimensions": len(vector),
                "local_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
