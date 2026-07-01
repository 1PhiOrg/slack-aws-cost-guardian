"""
S3-backed deep memory store (OKF-style concept files).

Deep memory is a directory of one-concept-per-file markdown documents with YAML
frontmatter, plus a navigable INDEX.md, living under a `memory/` prefix in the
same bucket as guardian-context.md. The curator writes it (P2); the conversation
path will navigate it (P3). See docs/MEMORY-SYSTEM.md.

Nothing reads concepts for analysis yet - this is the write side only.
"""

from __future__ import annotations

import boto3
import yaml
from botocore.exceptions import ClientError

INDEX_FILENAME = "INDEX.md"


def render_concept(frontmatter: dict, body: str) -> str:
    """Render a concept file: YAML frontmatter + markdown body."""
    fm = yaml.safe_dump(frontmatter or {}, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{(body or '').strip()}\n"


class DeepMemoryStore:
    """Read/write OKF concept files and INDEX.md in S3."""

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "memory/",
        s3_client: boto3.client | None = None,
    ):
        """
        Args:
            bucket_name: S3 bucket (same one as guardian-context.md).
            prefix: Key prefix for the memory directory (trailing slash enforced).
            s3_client: Optional boto3 S3 client. If None, creates one.
        """
        self.bucket = bucket_name
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"
        self.s3 = s3_client or boto3.client("s3")

    # -- keys ---------------------------------------------------------------

    def _safe_key(self, path: str) -> str | None:
        """
        Resolve a concept path to an S3 key. The path comes from the LLM, so it
        is untrusted: reject absolute paths, traversal, and directory-like paths.
        Returns None if the path is unsafe.
        """
        rel = path or ""
        if not rel or rel.startswith("/") or rel.endswith("/") or ".." in rel.split("/"):
            return None
        return self.prefix + rel

    # -- raw get/put --------------------------------------------------------

    def _get(self, key: str) -> str:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code", "") == "NoSuchKey":
                return ""
            raise

    def _put(self, key: str, content: str) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
        )

    # -- index --------------------------------------------------------------

    def read_index(self) -> str:
        return self._get(self.prefix + INDEX_FILENAME)

    def write_index(self, content: str) -> None:
        self._put(self.prefix + INDEX_FILENAME, content)

    # -- concepts -----------------------------------------------------------

    def list_concept_paths(self) -> list[str]:
        """List concept paths (relative to the prefix), excluding INDEX.md."""
        paths: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict = {"Bucket": self.bucket, "Prefix": self.prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self.s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                rel = obj["Key"][len(self.prefix):]
                if rel and rel != INDEX_FILENAME and not obj["Key"].endswith("/"):
                    paths.append(rel)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return paths

    def read_concept(self, path: str) -> str:
        key = self._safe_key(path)
        return self._get(key) if key else ""

    def read_all_concepts(self) -> dict[str, str]:
        """Map of concept path -> file content for every concept."""
        return {p: self.read_concept(p) for p in self.list_concept_paths()}

    def write_concept(self, path: str, content: str) -> bool:
        """Write a concept file. Returns False if the path was unsafe."""
        key = self._safe_key(path)
        if not key:
            return False
        self._put(key, content)
        return True