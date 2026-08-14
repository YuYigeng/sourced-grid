from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path


def request_json(url: str, method: str = "GET", payload: object | None = None) -> object:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SourcedGrid 100-row release benchmark")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--input", type=Path, default=Path("benchmarks/repositories-100.txt"))
    parser.add_argument("--budget", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    repositories = [line.strip() for line in args.input.read_text().splitlines() if line.strip()]
    if len(repositories) != 100:
        raise SystemExit(f"Expected exactly 100 repositories, got {len(repositories)}")
    started = time.perf_counter()
    grid = request_json(f"{args.api}/v1/templates/github-repository-radar/create-grid", "POST")
    assert isinstance(grid, dict)
    request_json(f"{args.api}/v1/grids/{grid['id']}/import", "POST", {"values": repositories})
    run = request_json(
        f"{args.api}/v1/grids/{grid['id']}/runs",
        "POST",
        {"budget_usd": args.budget, "force_refresh": True},
    )
    assert isinstance(run, dict)
    samples: list[float] = []
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        snapshot = request_json(f"{args.api}/v1/runs/{run['id']}")
        assert isinstance(snapshot, dict)
        samples.append(float(snapshot["completed_tasks"]) + float(snapshot["failed_tasks"]))
        if snapshot["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            elapsed = time.perf_counter() - started
            print(
                json.dumps(
                    {
                        "run_id": run["id"],
                        "status": snapshot["status"],
                        "elapsed_seconds": round(elapsed, 2),
                        "tasks": snapshot["total_tasks"],
                        "completed": snapshot["completed_tasks"],
                        "failed": snapshot["failed_tasks"],
                        "skipped": snapshot["skipped_tasks"],
                        "poll_progress_median": statistics.median(samples),
                    },
                    indent=2,
                )
            )
            return
        time.sleep(2)
    raise SystemExit("Benchmark timed out")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"API error {exc.code}: {exc.read().decode(errors='replace')}") from exc
