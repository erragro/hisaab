"""
A tiny in-memory stand-in for the Firestore Admin client — just the subset
app/repo.py and app/limits.py actually use. Not thread-safe, not complete;
enough to test our code without an emulator.
"""

from __future__ import annotations

import uuid
from typing import Optional

from google.cloud import firestore

_DESC = firestore.Query.DESCENDING


class AlreadyExists(Exception):
    pass


def _is_increment(v) -> bool:
    return type(v).__name__ == "Increment"


class Snapshot:
    def __init__(self, ref: "DocRef", data: Optional[dict]):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Count:
    def __init__(self, n: int):
        self._n = n

    def get(self):
        class _V:
            def __init__(self, v):
                self.value = v
        return [[_V(self._n)]]


class Query:
    def __init__(self, col: "Collection", order=None, direction="ASCENDING", limit_n=None):
        self._col = col
        self._order = order
        self._dir = direction
        self._limit = limit_n

    def order_by(self, field, direction="ASCENDING"):
        return Query(self._col, field, str(direction), self._limit)

    def limit(self, n):
        return Query(self._col, self._order, self._dir, n)

    def _rows(self):
        items = list(self._col._docs.items())
        if self._order:
            items.sort(key=lambda kv: kv[1].get(self._order))
            if "DESC" in self._dir:
                items.reverse()
        if self._limit is not None:
            items = items[: self._limit]
        return items

    def stream(self):
        for doc_id, data in self._rows():
            yield Snapshot(self._col.document(doc_id), dict(data))

    def get(self):
        return list(self.stream())

    def count(self):
        return _Count(len(self._col._docs))


class Collection(Query):
    def __init__(self, store: dict, path: tuple):
        super().__init__(self, None, "ASCENDING", None)
        self._store = store
        self._path = path
        self._col = self
        store.setdefault(path, {})     # docs: {id: data}
        store.setdefault(("__sub__", path), {})  # subcollections registry

    @property
    def _docs(self) -> dict:
        return self._store[self._path]

    def document(self, doc_id: Optional[str] = None) -> "DocRef":
        return DocRef(self._store, self._path + (doc_id or uuid.uuid4().hex,))


class DocRef:
    def __init__(self, store: dict, path: tuple):
        self._store = store
        self._path = path
        self.id = path[-1]

    # -- helpers
    def _coldict(self) -> dict:
        return self._store.setdefault(self._path[:-1], {})

    def _apply(self, existing: Optional[dict], data: dict, merge: bool) -> dict:
        base = dict(existing) if (existing and merge) else {}
        for k, v in data.items():
            base[k] = (base.get(k, 0) + v.value) if _is_increment(v) else v
        return base

    # -- API
    def get(self) -> Snapshot:
        return Snapshot(self, self._coldict().get(self.id))

    def set(self, data: dict, merge: bool = False):
        cur = self._coldict().get(self.id)
        self._coldict()[self.id] = self._apply(cur, data, merge)

    def update(self, data: dict):
        if self.id not in self._coldict():
            raise KeyError(self.id)
        self._coldict()[self.id] = self._apply(self._coldict()[self.id], data, True)

    def create(self, data: dict):
        if self.id in self._coldict():
            raise AlreadyExists(self.id)
        self._coldict()[self.id] = dict(data)

    def delete(self):
        self._coldict().pop(self.id, None)

    def collection(self, name: str) -> Collection:
        return Collection(self._store, self._path + (name,))

    def collections(self):
        prefix = self._path
        seen = set()
        for path in list(self._store):
            if path and path[0] == "__sub__":
                continue
            if len(path) == len(prefix) + 1 and path[:-1] == prefix and self._store[path]:
                if path[-1] not in seen:
                    seen.add(path[-1])
                    yield Collection(self._store, path)


class FakeClient:
    def __init__(self):
        self._store: dict = {}

    def collection(self, name: str) -> Collection:
        return Collection(self._store, (name,))
