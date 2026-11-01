from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from doc_extractor import __version__
from doc_extractor.api import (
    EXPORT_FORMATS,
    extract_files,
    load_batch,
    load_batch_by_id,
    load_latest_batch,
    save_batch,
    export_batch,
)
from doc_extractor.core.batch_io import resolve_output_root
from doc_extractor.core.pdf_parser import PARSE_MODES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="项目一：综合环境数据提取系统命令行接口",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    extract_parser = subparsers.add_parser(
        "extract",
        help="提取 Word/PDF 并保存批次",
    )
    extract_parser.add_argument(
        "--input",
        "-i",
        action="append",
        required=True,
        metavar="PATH",
        help="输入文件，可重复指定多个文件",
    )
    extract_parser.add_argument(
        "--mode",
        choices=PARSE_MODES,
        default=PARSE_MODES[0],
        help="PDF 解析模式（默认：local_gpu）",
    )
    extract_parser.add_argument(
        "--output-root",
        metavar="DIR",
        help="输出根目录（默认：项目 output 目录）",
    )
    extract_parser.add_argument(
        "--save-format",
        action="append",
        choices=EXPORT_FORMATS,
        dest="save_formats",
        help="提取后额外保存的格式，可重复指定（默认：json）",
    )
    extract_parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="PDF 渲染 DPI（默认：200）",
    )
    extract_parser.add_argument(
        "--request-timeout",
        type=float,
        default=300.0,
        help="云端 API 单次请求超时秒数",
    )
    extract_parser.add_argument(
        "--poll-timeout",
        type=float,
        default=600.0,
        help="云端 API 轮询超时秒数",
    )
    extract_parser.add_argument(
        "--quiet",
        action="store_true",
        help="不输出提取进度",
    )
    extract_parser.set_defaults(handler=_handle_extract)

    export_parser = subparsers.add_parser(
        "export",
        help="从已保存批次导出指定格式",
    )
    export_parser.add_argument(
        "--format",
        "-f",
        required=True,
        choices=EXPORT_FORMATS,
        help="导出格式",
    )
    export_parser.add_argument(
        "--batch-id",
        help="指定批次 ID；省略时使用最新批次",
    )
    export_parser.add_argument(
        "--batch-file",
        metavar="PATH",
        help="指定批次 JSON 文件；省略时从输出目录读取",
    )
    export_parser.add_argument(
        "--output-root",
        metavar="DIR",
        help="输出根目录（默认：项目 output 目录）",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        help="指定导出文件路径；默认写入对应格式目录",
    )
    export_parser.set_defaults(handler=_handle_export)

    return parser


def _handle_extract(args: argparse.Namespace) -> int:
    paths = [Path(item).expanduser() for item in args.input]
    progress = None
    if not args.quiet:
        def progress(current: int, total: int, message: str) -> None:
            print(f"[{current}/{total}] {message}")

    batch = extract_files(
        paths,
        mode=args.mode,
        structure_dpi=args.dpi,
        request_timeout=args.request_timeout,
        poll_timeout=args.poll_timeout,
        progress_callback=progress,
    )
    formats = tuple(args.save_formats or ["json"])
    outputs = save_batch(batch, args.output_root, formats=formats)

    print(f"批次 ID：{batch.batch_id}")
    print(f"提取时间：{batch.extracted_at}")
    print(f"文档数量：{batch.document_count}")
    print(f"记录数量：{batch.record_count}")
    print(f"环境记录数：{batch.environmental.record_count}")
    for document in batch.documents:
        status = "失败" if document.error else "成功"
        print(
            f"- {document.source_name} [{status}] "
            f"记录 {document.record_count} 表格 {document.table_count}"
        )
        if document.error:
            print(f"  错误：{document.error}")
        for warning in document.warnings:
            print(f"  提示：{warning}")
    print(f"输出根目录：{resolve_output_root(args.output_root)}")
    for name, path in outputs.items():
        print(f"- {name}: {path}")

    return 0 if any(document.succeeded for document in batch.documents) else 1


def _handle_export(args: argparse.Namespace) -> int:
    if args.batch_file:
        batch = load_batch(args.batch_file)
    elif args.batch_id:
        batch = load_batch_by_id(args.batch_id, args.output_root)
    else:
        batch = load_latest_batch(args.output_root)

    output = export_batch(
        batch,
        args.format,
        args.output_root,
        args.output,
    )
    print(f"批次 ID：{batch.batch_id}")
    print(f"导出文件：{output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        parser.print_help()
        return 0
    args = parser.parse_args(arguments)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        return int(args.handler(args))
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
