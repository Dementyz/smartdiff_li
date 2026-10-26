from smartdiff_li.analysis import analyze_diff
from smartdiff_li.gitutil import GitError, resolve_revisions

import pytest

CORE = '''\
def process(data, legacy=False):
    return [d * 2 for d in data]


def helper(x):
    return x + 1
'''

API = '''\
from core import process, helper


def handle(request):
    return process(request) + helper(1)
'''

TEST = '''\
from api import handle


def test_handle():
    assert handle([1]) == [3]
'''


def base_repo(repo):
    repo.write("core.py", CORE)
    repo.write("api.py", API)
    repo.write("tests/test_api.py", TEST)
    repo.commit("init")
    return repo


def analyze(repo, *revs, depth=3):
    base, head, label = resolve_revisions(repo.root, list(revs))
    return analyze_diff(repo.root, base, head, label, depth)


def by_symbol(result):
    return {i.change.qualname: i for i in result.items}


def test_no_changes(repo):
    base_repo(repo)
    result = analyze(repo)
    assert result.items == [] and result.risk.level == "low"


def test_formatting_only_change_is_low_risk(repo):
    base_repo(repo)
    repo.write("core.py", CORE.replace("x + 1", "x   +   1  # c").replace("[d", "[ d"))
    result = analyze(repo)
    assert result.items == []
    assert result.cosmetic == ["core.py"]
    assert result.risk.level == "low"


def test_body_change_reports_callers_and_tests(repo):
    base_repo(repo)
    repo.write("core.py", CORE.replace("d * 2", "d * 3"))
    result = analyze(repo)
    item = by_symbol(result)["process"]
    assert item.change.change == "body"
    assert [(i.module, i.symbol, i.depth) for i in item.impacted] == [
        ("api", "handle", 1), ("test_api", "test_handle", 2)]
    assert result.tests == ["tests/test_api.py"]
    assert result.dependents == {"api": 1, "test_api": 2}


def test_depth_limits_transitive_impact(repo):
    base_repo(repo)
    repo.write("core.py", CORE.replace("d * 2", "d * 3"))
    item = by_symbol(analyze(repo, depth=1))["process"]
    assert [i.symbol for i in item.impacted] == ["handle"]


def test_removed_function_with_remaining_callers_is_broken(repo):
    base_repo(repo)
    repo.write("core.py", CORE.split("def helper")[0])
    result = analyze(repo)
    item = by_symbol(result)["helper"]
    assert item.change.change == "removed"
    assert [(i.symbol, i.certain) for i in item.impacted] == [("handle", True)]
    assert item.broken == 1
    assert result.risk.level in ("high", "critical")


def test_removed_name_still_used_in_same_module(repo):
    base_repo(repo)
    repo.write("core.py", CORE + "\n\ndef both():\n    return helper(2)\n")
    repo.commit("both")
    repo.write("core.py", CORE.split("def helper")[0] + "\n\ndef both():\n    return helper(2)\n")
    item = by_symbol(analyze(repo))["helper"]
    assert ("core", "both") in {(i.module, i.symbol) for i in item.impacted}


def test_breaking_signature_change(repo):
    base_repo(repo)
    repo.write("core.py", CORE.replace("(data, legacy=False)", "(data, mode)"))
    result = analyze(repo)
    item = by_symbol(result)["process"]
    assert item.change.change == "signature" and item.change.breaking
    assert "added params: mode (required)" in item.change.details
    assert result.risk.level != "low"


def test_compatible_signature_change_scores_lower(repo):
    base_repo(repo)
    repo.write("core.py", CORE.replace("legacy=False)", "legacy=False, extra=1)"))
    item = by_symbol(analyze(repo))["process"]
    assert item.change.change == "signature" and not item.change.breaking


def test_function_moved_to_another_module(repo):
    base_repo(repo)
    big = "def big(n):\n    total = 0\n    for i in range(n):\n        total += i * 2\n    return total\n"
    repo.write("core.py", CORE + "\n\n" + big)
    repo.commit("big")
    repo.write("core.py", CORE)
    repo.write("other.py", big)
    result = analyze(repo)
    moved = by_symbol(result)["big"]
    assert moved.change.change == "moved" and moved.change.moved_to == "other:big"
    assert "big" not in {i.change.qualname for i in result.items if i.change.change == "added"}


def test_deleted_file_reports_broken_imports(repo):
    base_repo(repo)
    repo.remove("core.py")
    result = analyze(repo)
    item = by_symbol(result)["<file>"]
    assert item.change.change == "removed" and item.change.path == "core.py"
    assert [(i.module, i.lineno) for i in item.impacted] == [("api", 1)]
    assert result.risk.level in ("high", "critical")


def test_added_file_and_untracked_files(repo):
    base_repo(repo)
    repo.write("new.py", "def f(): pass\n")
    result = analyze(repo)
    (item,) = result.items
    assert item.change.kind == "file" and item.change.change == "added"
    assert item.change.details == "1 symbol"


def test_syntax_error_is_critical(repo):
    base_repo(repo)
    repo.write("core.py", "def process(:\n")
    result = analyze(repo)
    assert result.unparsable == ["core.py"]
    assert result.risk.level == "critical"
    assert "syntax error in core.py" in result.risk.reasons


def test_non_python_files_are_listed_not_analyzed(repo):
    base_repo(repo)
    repo.write("README.md", "hi\n")
    result = analyze(repo)
    assert result.other_files == ["README.md"] and result.items == []


def test_revision_ranges(repo):
    base_repo(repo)
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("core.py", CORE.replace("d * 2", "d * 3"))
    repo.commit("feature")
    repo.git("checkout", "-q", "main")
    repo.write("other.py", "x = 1\n")
    repo.commit("main moved on")
    for revs in (["main", "feature"], ["main..feature"]):
        # прямое сравнение: other.py есть в main, но нет в feature
        assert set(by_symbol(analyze(repo, *revs))) == {"process", "<file>"}
    merge_base = analyze(repo, "main...feature")
    assert set(by_symbol(merge_base)) == {"process"}
    assert merge_base.label == "main..feature"


def test_unknown_revision(repo):
    base_repo(repo)
    with pytest.raises(GitError):
        resolve_revisions(repo.root, ["nope"])
