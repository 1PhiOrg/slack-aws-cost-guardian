"""Unit tests for the S3-backed deep memory store (P2)."""

import pytest
from botocore.exceptions import ClientError

from slack_aws_cost_guardian.storage.deep_memory import DeepMemoryStore, render_concept


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """Minimal in-memory stand-in for a boto3 S3 client."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self.objects[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        contents = [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]
        return {"Contents": contents, "IsTruncated": False}


@pytest.fixture
def store():
    return DeepMemoryStore("bucket", s3_client=_FakeS3())


# -- render_concept ---------------------------------------------------------


def test_render_concept_has_frontmatter_and_body():
    out = render_concept(
        {"id": "nat-baseline", "type": "service", "tags": ["vpc"]},
        "NAT is accepted.\n\n**Why:** confirmed.",
    )
    assert out.startswith("---\n")
    assert "id: nat-baseline" in out
    assert "type: service" in out
    assert out.count("---") == 2
    assert "NAT is accepted." in out
    assert out.endswith("\n")


# -- concepts ---------------------------------------------------------------


def test_concept_round_trip(store):
    store.write_concept("services/nat.md", "---\nid: nat\n---\n\nbody")
    assert store.read_concept("services/nat.md") == "---\nid: nat\n---\n\nbody"


def test_missing_concept_returns_empty(store):
    assert store.read_concept("services/nope.md") == ""


def test_list_excludes_index(store):
    store.write_concept("services/nat.md", "a")
    store.write_concept("patterns/spike.md", "b")
    store.write_index("# index")
    paths = store.list_concept_paths()
    assert set(paths) == {"services/nat.md", "patterns/spike.md"}
    assert "INDEX.md" not in paths


def test_read_all_concepts(store):
    store.write_concept("services/nat.md", "a")
    store.write_concept("accounts/prod.md", "b")
    assert store.read_all_concepts() == {"accounts/prod.md": "b", "services/nat.md": "a"}


# -- index ------------------------------------------------------------------


def test_index_empty_by_default(store):
    assert store.read_index() == ""


def test_index_round_trip(store):
    store.write_index("# Deep memory index\n- services/nat.md")
    assert "services/nat.md" in store.read_index()


# -- path safety ------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../secrets.md", "/etc/passwd", "a/../../x.md", "", "dir/"])
def test_unsafe_paths_rejected(store, bad):
    assert store.write_concept(bad, "x") is False


def test_prefix_trailing_slash_enforced():
    s = DeepMemoryStore("bucket", prefix="memory", s3_client=_FakeS3())
    assert s.prefix == "memory/"