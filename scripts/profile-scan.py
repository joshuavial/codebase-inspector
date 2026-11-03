"""Profile scans of a disposable generic fixture; never accepts an existing repo."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import make_repo
from cbi import tasks
from cbi.cli import main, scan


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    # Each run has identical source bytes and new model/cache directories.
    base = Path(tempfile.mkdtemp(prefix="cbi-profile-"))
    source = {}
    for pkg in range(6):
        source[f"pkg{pkg}/package.json"] = json.dumps({"name": f"pkg{pkg}", "private": True})
        for n in range(250):
            source[f"pkg{pkg}/f{n:03}.py"] = (
                f"from .f{(n+1)%250:03} import helper as other\n"
                "def helper(value):\n    return value + 1\n"
                "def run(value):\n    return other(helper(value))\n")
    root = make_repo.__wrapped__(base)(source, name="repo")
    os.environ["CBI_CACHE_DIR"] = str(base / "cache")
    os.environ["CBI_NO_UPDATE_CHECK"] = "1"
    os.chdir(root)
    main(["init"])
    main(["team", "init"])
    out = root / ".cbi"
    results = {}
    profile = cProfile.Profile()
    for phase in ("cold", "source", "judgement"):
        if phase == "source":
            path = root / "pkg0/f000.py"
            path.write_text(path.read_text() + "# changed\n")
        elif phase == "judgement":
            with (out / "answers.jsonl").open("a") as stream:
                stream.write(json.dumps({"kind": "summarise-files", "key": "historical-only",
                                         "protocol": tasks.PROTOCOL_VERSION,
                                         "answer": "Historical description."}) + "\n")
        start = time.perf_counter()
        if phase == "cold":
            profile.enable()
        scan(root, out)
        if phase == "cold":
            profile.disable()
        results[phase] = time.perf_counter() - start
    profile.dump_stats(str(args.output / "cold.prof"))
    with (args.output / "cold-profile.txt").open("w") as stream:
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(35)
    (args.output / "timings.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    run()
