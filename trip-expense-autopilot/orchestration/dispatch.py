import concurrent.futures as cf
import json
import sys
from pathlib import Path

from llm import ask, extract_files

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "SPEC.md").read_text()
SYSTEM = (
    "You are a senior Python engineer. Output ONLY files, each as:\n=== FILE: <relative/path> ===\n```python\n<content>\n```\n"
    "No prose. No code comments. Python 3.12, type hints, stdlib + allowed deps only. Code must be complete and runnable."
)


def run(job):
    name, model, prompt = job["name"], job["model"], job["prompt"]
    ctx = "".join(f"\n=== CURRENT FILE: {f} ===\n```\n{(ROOT / f).read_text()}\n```\n" for f in job.get("files", []))
    text = ask(model, f"SPEC:\n{SPEC}\n{ctx}\nTASK:\n{prompt}", task=name, system=job.get("system", SYSTEM))
    out = ROOT / "orchestration" / "out" / f"{name}.{model.replace('/', '_')}.md"
    out.write_text(text)
    for rel, body in extract_files(text).items():
        if job.get("apply", True):
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)
    return name, model, list(extract_files(text))


if __name__ == "__main__":
    jobs = json.loads(Path(sys.argv[1]).read_text())
    if len(sys.argv) > 2:
        jobs = [j for j in jobs if j["name"] in sys.argv[2:]]
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        for r in ex.map(run, jobs):
            print(r)
