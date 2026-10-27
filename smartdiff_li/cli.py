import argparse
import sys
from pathlib import Path

from . import core
from .analysis import analyze_diff
from .gitutil import GitError, repo_root, resolve_revisions
from .report import format_json, format_text
from .risk import LEVEL_ORDER

# Функция для анализа проекта 
def analyze_project(proj_path):
    if proj_path.exists():
        if proj_path.is_dir():
            print(f"Analyzing {proj_path}")
            analyze_directory(proj_path)
        else:
            print("Not is project")
    else:
        print("Unknown path")

# Анализируем все файлы в репозитории и в подкатегориях
def analyze_directory(path: Path):
    py_files = path.rglob('*.py')
    files = []
    for path_obj in py_files:
        files.append(path_obj)

    print_directory(files)

def print_directory(directory):
    for py_obj in directory:
        print(py_obj)
        print('\n')
              

def build_parser():
    parser = argparse.ArgumentParser(prog="smartdiff", description="Static impact analysis for code changes")
    parser.add_argument("--version", action="version", version=f"smartdiff 0.1.0 (core: {core.backend()})")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="list Python files of a project")
    analyze.add_argument("path", type=Path)

    diff = commands.add_parser("diff", help="semantic diff with impact analysis and risk score")
    diff.add_argument("revs", nargs="*", metavar="REV",
                      help="BASE | BASE HEAD | BASE..HEAD | BASE...HEAD (default: HEAD vs working tree)")
    diff.add_argument("-C", "--path", type=Path, default=Path("."), help="repository path")
    diff.add_argument("--depth", type=int, default=3, help="how many call levels to follow (default: 3)")
    diff.add_argument("--format", choices=("text", "json"), default="text")
    diff.add_argument("--all", action="store_true", help="show every impacted symbol")
    diff.add_argument("--fail-on", choices=LEVEL_ORDER[1:], help="exit with code 2 at this risk level or higher")
    return parser


def run_diff(args):
    root = repo_root(args.path)
    base, head, label = resolve_revisions(root, args.revs)
    result = analyze_diff(root, base, head, label, depth=args.depth)
    if args.format == "json":
        print(format_json(result))
    else:
        print(format_text(result, show_all=args.all))
    if args.fail_on and LEVEL_ORDER.index(result.risk.level) >= LEVEL_ORDER.index(args.fail_on):
        return 2
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        analyze_project(proj_path=args.path)
        return 0
    try:
        return run_diff(args)
    except GitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
