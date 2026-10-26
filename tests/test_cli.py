import json

from smartdiff_li.cli import main


def make_repo(repo):
    repo.write("core.py", "def f(x):\n    return x\n")
    repo.write("api.py", "from core import f\n\ndef g():\n    return f(1)\n")
    repo.commit("init")
    repo.write("core.py", "def f(x, y):\n    return x\n")


def test_text_output(repo, capsys):
    make_repo(repo)
    assert main(["diff", "-C", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert "RISK" in out and "f (function)  signature changed [BREAKING]" in out
    assert "<- api.g" in out


def test_json_output(repo, capsys):
    make_repo(repo)
    assert main(["diff", "-C", str(repo.root), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    (change,) = data["changes"]
    assert change["symbol"] == "f" and change["breaking"] is True
    assert change["impacted"][0]["symbol"] == "g"


def test_fail_on(repo, capsys):
    make_repo(repo)
    assert main(["diff", "-C", str(repo.root), "--fail-on", "medium"]) == 2
    assert main(["diff", "-C", str(repo.root), "--fail-on", "critical"]) == 0


def test_not_a_repo(tmp_path, capsys):
    assert main(["diff", "-C", str(tmp_path)]) == 1
    assert "not inside a git repository" in capsys.readouterr().err


def test_analyze_lists_python_files(tmp_path, capsys):
    (tmp_path / "a.py").write_text("")
    assert main(["analyze", str(tmp_path)]) == 0
    assert "a.py" in capsys.readouterr().out
