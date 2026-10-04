"""Key-addressed spec patches (frozen contract, WP0).

Path segments name model fields; inside a keyed list (a list of objects with ``key``) the next
segment is an element's key. Scalar lists (e.g. ``detail_fields``) cannot be addressed inside;
they are replaced whole with ``set``.

Ops:
  set     path ends at a field (scalar, scalar list, or whole sub-object) or at a keyed-list
          element (replaced whole; its ``key`` must stay the same). A keyed list itself cannot be
          set; use add/remove per element.
  add     path ends at a keyed list; ``value`` is the new object with its own unused ``key``;
          ``before`` (optional) is an existing key to insert before, default append.
  remove  path ends at a keyed-list element (deleted) or at a nullable field (set to null).

Refused: changing an object's ``key`` or a capability's ``type`` (remove and add instead).
``apply_patch`` is atomic: it works on a copy, re-validates the result as a full BotSpec and with
``validate_spec`` (errors only; warnings pass), and returns a new spec or raises PatchError.
"""

import copy
import types
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict
from pydantic_core import to_jsonable_python

from app.botspec.models import AnyCapability, BotSpec
from app.botspec.validate import SpecIssue, parse_spec, validate_spec


class PatchOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["set", "add", "remove"]
    path: list[str]  # segments; an element of a keyed list is addressed by its key
    value: Any | None = None  # set: new value; add: the new object (must carry its own key)
    before: str | None = None  # add: insert before this key; default append


class PatchError(Exception):
    """A rejected op list. ``op_index`` is None when the combined result failed validation.

    code: invalid_op | path_not_found | invalid_target | key_change_forbidden |
          type_change_forbidden | duplicate_key | invalid_spec
    """

    def __init__(
        self,
        op_index: int | None,
        message: str,
        *,
        code: str = "invalid_op",
        issues: list[SpecIssue] | None = None,
    ) -> None:
        super().__init__(message if op_index is None else f"op {op_index}: {message}")
        self.op_index = op_index
        self.message = message
        self.code = code
        self.issues = issues or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_index": self.op_index,
            "code": self.code,
            "message": self.message,
            "issues": [i.model_dump() for i in self.issues],
        }


# --------------------------------------------------------------------------- schema shapes


@dataclass(frozen=True)
class Shape:
    """What a value at some path is, derived from the BotSpec annotations."""

    kind: Literal["model", "keyed_list", "scalar_list", "scalar"]
    models: tuple[type[BaseModel], ...] = ()  # model / keyed_list: candidate classes
    nullable: bool = False


def _strip(ann: Any) -> tuple[Any, bool]:
    """Remove Annotated wrappers and None from a union. Returns (inner, nullable)."""
    if get_origin(ann) is Annotated:
        return _strip(get_args(ann)[0])
    if get_origin(ann) in (Union, types.UnionType):
        args = get_args(ann)
        rest = [a for a in args if a is not type(None)]
        nullable = len(rest) < len(args)
        if len(rest) == 1:
            inner, n2 = _strip(rest[0])
            return inner, nullable or n2
        return tuple(_strip(a)[0] for a in rest), nullable
    return ann, False


def _models_of(inner: Any) -> tuple[type[BaseModel], ...]:
    cands = inner if isinstance(inner, tuple) else (inner,)
    if all(isinstance(c, type) and issubclass(c, BaseModel) for c in cands):
        return cands
    return ()


def shape_of(ann: Any) -> Shape:
    inner, nullable = _strip(ann)
    models = _models_of(inner)
    if models:
        return Shape("model", models, nullable)
    if get_origin(inner) is list:
        item_inner, _ = _strip(get_args(inner)[0])
        item_models = _models_of(item_inner)
        if item_models:
            return Shape("keyed_list", item_models, nullable)
        return Shape("scalar_list", (), nullable)
    return Shape("scalar", (), nullable)


ROOT = Shape("model", (BotSpec,))


def pick_model(models: tuple[type[BaseModel], ...], node: Any) -> type[BaseModel] | None:
    """Choose the class for a dict node; discriminated unions are resolved by ``type``."""
    if len(models) == 1:
        return models[0]
    if not isinstance(node, dict):
        return None
    for m in models:
        t = m.model_fields.get("type")
        if t is not None and node.get("type") in get_args(t.annotation):
            return m
    return None


def child(shape: Shape, node: Any, seg: str) -> tuple[Any, Shape]:
    """Descend one segment. Raises LookupError / TypeError with a readable message."""
    if node is None:
        raise LookupError("path goes through a null value")
    if shape.kind == "model":
        cls = pick_model(shape.models, node)
        if cls is None or not isinstance(node, dict):
            raise TypeError("cannot resolve object type")
        if seg not in cls.model_fields:
            raise LookupError(f"{cls.__name__} has no field '{seg}'")
        return node.get(seg), shape_of(cls.model_fields[seg].annotation)
    if shape.kind == "keyed_list":
        for elem in node:
            if isinstance(elem, dict) and elem.get("key") == seg:
                return elem, Shape("model", shape.models)
        raise LookupError(f"no element with key '{seg}'")
    raise TypeError("cannot address inside a scalar or scalar list; set it whole")


# --------------------------------------------------------------------------- application


class _OpFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _resolve_parent(data: dict[str, Any], path: list[str]) -> tuple[Any, Shape]:
    node: Any = data
    shape = ROOT
    for i, seg in enumerate(path):
        try:
            node, shape = child(shape, node, seg)
        except LookupError as exc:
            raise _OpFailure("path_not_found", f"{'/'.join(path[: i + 1])}: {exc}") from None
        except TypeError as exc:
            raise _OpFailure("invalid_target", f"{'/'.join(path[: i + 1])}: {exc}") from None
    return node, shape


def _element_index(lst: list[Any], key: str) -> int | None:
    return next((i for i, e in enumerate(lst) if isinstance(e, dict) and e.get("key") == key), None)


_CAPABILITY_CLASSES: frozenset[type[BaseModel]] = frozenset(_models_of(_strip(AnyCapability)[0]))


def _check_identity(old: Any, new: Any, cls: type[BaseModel] | None) -> None:
    """A replaced object keeps its key and, if it is a capability, its type."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    if "key" in old and new.get("key") != old["key"]:
        raise _OpFailure(
            "key_change_forbidden", "changing an object's key is not allowed; remove it and add a new one"
        )
    if cls in _CAPABILITY_CLASSES and new.get("type") != old.get("type"):
        raise _OpFailure(
            "type_change_forbidden", "changing a capability's type is not allowed; remove and add instead"
        )


def _apply_one(data: dict[str, Any], op: PatchOp) -> None:
    if not op.path:
        raise _OpFailure("invalid_target", "path must not be empty")
    if op.before is not None and op.op != "add":
        raise _OpFailure("invalid_op", "'before' is only valid for add")
    value = copy.deepcopy(to_jsonable_python(op.value))
    parent, pshape = _resolve_parent(data, op.path[:-1])
    last = op.path[-1]
    where = "/".join(op.path)

    if pshape.kind == "keyed_list":
        idx = _element_index(parent, last)
        if op.op == "add":
            raise _OpFailure("invalid_target", f"{where}: add must target the list, not an element")
        if idx is None:
            raise _OpFailure("path_not_found", f"{where}: no element with key '{last}'")
        if op.op == "remove":
            del parent[idx]
            return
        if not isinstance(value, dict):
            raise _OpFailure("invalid_op", f"{where}: set on a list element needs an object value")
        value.setdefault("key", last)
        _check_identity(parent[idx], value, pick_model(pshape.models, parent[idx]))
        parent[idx] = value
        return

    if pshape.kind != "model":
        raise _OpFailure("invalid_target", f"{where}: cannot address inside a scalar list")
    try:
        current, fshape = child(pshape, parent, last)
    except LookupError as exc:
        raise _OpFailure("path_not_found", f"{where}: {exc}") from None
    except TypeError as exc:
        raise _OpFailure("invalid_target", f"{where}: {exc}") from None

    if op.op == "set":
        if last == "key" and value != current:
            raise _OpFailure(
                "key_change_forbidden", "changing an object's key is not allowed; remove it and add a new one"
            )
        if last == "type" and value != current and (pick_model(pshape.models, parent) in _CAPABILITY_CLASSES):
            raise _OpFailure(
                "type_change_forbidden", "changing a capability's type is not allowed; remove and add instead"
            )
        if fshape.kind == "keyed_list":
            raise _OpFailure("invalid_target", f"{where}: a keyed list cannot be set whole; use add/remove")
        if fshape.kind == "model" and isinstance(current, dict) and isinstance(value, dict):
            _check_identity(current, value, pick_model(fshape.models, current))
        parent[last] = value
    elif op.op == "add":
        if fshape.kind != "keyed_list":
            raise _OpFailure("invalid_target", f"{where}: add targets a keyed list")
        if not isinstance(value, dict) or not isinstance(value.get("key"), str):
            raise _OpFailure("invalid_op", f"{where}: added value must be an object with a 'key'")
        if _element_index(current, value["key"]) is not None:
            raise _OpFailure("duplicate_key", f"{where}: key '{value['key']}' already exists")
        if op.before is None:
            current.append(value)
        else:
            pos = _element_index(current, op.before)
            if pos is None:
                raise _OpFailure("path_not_found", f"{where}: no element '{op.before}' for 'before'")
            current.insert(pos, value)
    else:  # remove
        if fshape.kind == "keyed_list":
            raise _OpFailure("invalid_target", f"{where}: remove an element by its key instead")
        if not fshape.nullable:
            raise _OpFailure("invalid_target", f"{where}: field is not optional and cannot be removed")
        parent[last] = None


def apply_patch(spec: BotSpec, ops: list[PatchOp]) -> BotSpec:
    """Apply ``ops`` atomically; return a new, valid spec or raise PatchError."""
    data = spec.model_dump(mode="json")
    for i, raw in enumerate(ops):
        try:
            op = raw if isinstance(raw, PatchOp) else PatchOp.model_validate(raw)
        except Exception as exc:  # malformed op object
            raise PatchError(i, f"malformed op: {exc}", code="invalid_op") from None
        try:
            _apply_one(data, op)
        except _OpFailure as exc:
            raise PatchError(i, str(exc), code=exc.code) from None
    new, issues = parse_spec(data)
    if new is None:
        raise PatchError(None, "patched spec fails schema validation", code="invalid_spec", issues=issues)
    errors = [i for i in validate_spec(new) if i.severity == "error"]
    if errors:
        raise PatchError(None, "patched spec fails semantic validation", code="invalid_spec", issues=errors)
    return new
