"""整批导出文件、校验清单及完整性读取；默认拒绝覆盖已有输出目录。"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .export import validate_exports
from .export_schema import EXPORT_KINDS, EXPORT_VERSION, export_schema
from .extraction import canonical_json
from .serialization import require_fields


def _encode(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _manifest(bundle, files, papers):
    diagnostics = {}
    for document in bundle.values():
        for section in document["papers"]:
            diagnostics[section["input"]["openalex_id"]] = section["diagnostics"]
    return {
        "format_version": EXPORT_VERSION,
        "contract_status": "draft",
        "files": {
            name: hashlib.sha256(body).hexdigest() for name, body in files.items()
        },
        "processed_papers": len(papers),
        "counts": {status: document["counts"] for status, document in bundle.items()},
        "diagnostics": sum(len(values) for values in diagnostics.values()),
        "evaluation_status": "not_evaluated",
    }


def export_files(bundle: dict, papers) -> dict[str, bytes]:
    validate_exports(bundle, papers)
    files = {status + ".json": _encode(bundle[status]) for status in EXPORT_KINDS}
    files["schema.json"] = _encode(export_schema())
    files["manifest.json"] = _encode(_manifest(bundle, files, papers))
    return files


def write_exports(destination: str | Path, bundle: dict, papers) -> Path:
    files = export_files(bundle, papers)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(
            "Export destination exists; choose a new output directory"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(dir=destination.parent, prefix=".knowledge-export-")
    )
    try:
        for name, body in files.items():
            with (temporary / name).open("wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
        os.rename(temporary, destination)
    finally:
        # 只清理本次生成的同级临时目录及已知文件，不递归删除任何用户目录。
        if temporary.exists() and temporary.resolve().parent == destination.parent:
            for name in files:
                (temporary / name).unlink(missing_ok=True)
            temporary.rmdir()
    return destination


def load_exports(directory: str | Path, papers) -> dict:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require_fields(
        manifest,
        (
            "format_version",
            "contract_status",
            "files",
            "processed_papers",
            "counts",
            "diagnostics",
            "evaluation_status",
        ),
    )
    names = [status + ".json" for status in EXPORT_KINDS] + ["schema.json"]
    require_fields(manifest["files"], names)
    files = {}
    for name in names:
        body = (directory / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != manifest["files"][name]:
            raise ValueError("Export checksum mismatch: " + name)
        files[name] = body
    schema = json.loads(files["schema.json"].decode("utf-8"))
    if schema != export_schema():
        raise ValueError("Unsupported or changed export schema")
    bundle = {
        status: json.loads(files[status + ".json"].decode("utf-8"))
        for status in EXPORT_KINDS
    }
    validate_exports(bundle, papers)
    if canonical_json(manifest) != canonical_json(_manifest(bundle, files, papers)):
        raise ValueError("Export manifest does not match files or input scope")
    return bundle
