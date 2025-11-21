#!/usr/bin/env python3

import argparse
import csv
import datetime as dt
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join k6 CSV with Prometheus CPU and replicas into an enhanced time series report")
    parser.add_argument("--k6-csv", required=True, help="Path to k6 CSV export (e.g., k6/reports/context_hpa_vu_50_10m.csv)")
    parser.add_argument("--prom", required=True, help="Prometheus base URL, e.g., http://kube-prometheus-stack-prometheus.monitoring.svc:9090")
    parser.add_argument("--namespace", default="socialnetwork", help="Kubernetes namespace for targets")
    parser.add_argument("--services", nargs="+", default=["compose-post-service", "text-service", "user-mention-service"], help="Service/deployment names")
    parser.add_argument("--bucket-sec", type=int, default=10, help="Bucket size in seconds for aggregation")
    parser.add_argument("--out", required=True, help="Output CSV path (e.g., k6/reports/enhanced/enhanced.csv)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    return parser.parse_args()


def read_k6_csv(path: str, bucket_sec: int):
    # Aggregate by bucket: count, failures, durations for percentiles
    per_bucket = defaultdict(lambda: {"durations": [], "reqs": 0, "fails": 0})

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            metric_name = row.get("metric_name", "")
            # we consider only http_req_duration rows for latency; http_reqs for count
            try:
                ts = int(float(row["timestamp"]))
            except Exception:
                continue
            bucket = ts - (ts % bucket_sec)

            if metric_name == "http_reqs":
                per_bucket[bucket]["reqs"] += 1
                # failure can be inferred from status != 200 or expected_response == false or error present
                status = row.get("status", "")
                expected = row.get("expected_response", "true").lower()
                error = row.get("error", "")
                is_fail = False
                if status and status != "200":
                    is_fail = True
                elif expected in ("false", "0"): 
                    is_fail = True
                elif error:
                    is_fail = True
                if is_fail:
                    per_bucket[bucket]["fails"] += 1
            elif metric_name == "http_req_duration":
                try:
                    # k6 exports duration in ms by default
                    dur_ms = float(row["metric_value"])  # milliseconds
                    per_bucket[bucket]["durations"].append(dur_ms)
                except Exception:
                    pass

    if not per_bucket:
        raise SystemExit("No data parsed from k6 CSV; ensure the file is correct.")

    start = min(per_bucket.keys())
    end = max(per_bucket.keys())
    return per_bucket, start, end


def prom_query_range(prom_url: str, query: str, start: int, end: int, step: int = 10):
    params = {
        "query": query,
        "start": str(start),
        "end": str(end),
        "step": str(step),
    }
    url = f"{prom_url.rstrip('/')}/api/v1/query_range?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload["data"]["result"]


def prom_has_data(prom_url: str, namespace: str, start: int, end: int) -> bool:
    # Quick existence check for either container CPU or kube_pod_info series in window
    import urllib.request as _rq
    import urllib.parse as _up
    base = prom_url.rstrip('/') + "/api/v1/series"
    params = {
        "match[]": [
            f"container_cpu_usage_seconds_total{{namespace=\"{namespace}\"}}",
            f"kube_pod_info{{namespace=\"{namespace}\"}}",
        ],
        "start": str(start),
        "end": str(end),
    }
    # Manually build query string with repeated match[]
    q = _up.urlencode([(k, v) for k, vals in params.items() for v in (vals if isinstance(vals, list) else [vals])])
    url = f"{base}?{q}"
    try:
        with _rq.urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("status") != "success":
            return False
        data = payload.get("data", [])
        return bool(data)
    except Exception:
        return False


def percentile(sorted_values, p):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1


def main():
    args = parse_args()

    per_bucket, start, end = read_k6_csv(args.k6_csv, args.bucket_sec)
    if args.debug:
        import datetime as _dt
        sys.stderr.write(
            f"k6 buckets: {len(per_bucket)}; bucket_sec={args.bucket_sec}; "
            f"start={start}({_dt.datetime.utcfromtimestamp(start).isoformat()}Z) "
            f"end={end}({_dt.datetime.utcfromtimestamp(end).isoformat()}Z)\n"
        )
        sys.stderr.write(f"services: {', '.join(args.services)}; namespace={args.namespace}\n")

    # Build PromQL for the three dashboard-aligned views per service:
    # 1) CPU total mcores (5m): sum(rate(container_cpu_usage_seconds_total{namespace="ns", pod=~"<pod_prefix>.*"}[5m])) * 1000
    # 2) Replicas via kube_pod_info (count of pods matching pod regex): count by (app) (kube_pod_info{pod=~"<pod_prefix>.*"})
    # 3) CPU utilization % (2m): (sum(rate(container_cpu_usage_seconds_total{namespace="ns", container=~"<container_prefix>.*"}[2m])) / sum(kube_pod_container_resource_limits{resource="cpu", namespace="ns", container=~"<container_prefix>.*"})) * 100

    def pod_prefix_for(deploy_name: str) -> str:
        # Map deployment name to pod prefix as used in dashboard queries
        if deploy_name.endswith("-service"):
            return deploy_name[:-8]  # strip "-service"
        return deploy_name

    def container_prefix_for(deploy_name: str) -> str:
        # Explicit mapping to match dashboard's container regexes
        mapping = {
            "compose-post-service": "compose",
            "nginx-thrift": "nginx",
            "text-service": "text",
            "user-mention-service": "user-mention",
        }
        return mapping.get(deploy_name, deploy_name)

    cpu_mcores_queries = {}
    replica_queries = {}
    cpu_util_pct_queries = {}
    for svc in args.services:
        pod_re = f"{pod_prefix_for(svc)}.*"
        container_re = f"{container_prefix_for(svc)}.*"

        cpu_mcores_q = (
            f"sum (rate(container_cpu_usage_seconds_total{{namespace=\"{args.namespace}\", pod=~\"{pod_re}\"}}[5m])) * 1000"
        )
        rep_q = (
            f"count by (app) (kube_pod_info{{pod=~\"{pod_re}\"}})"
        )
        util_q = (
            "("
            f"sum(rate(container_cpu_usage_seconds_total{{namespace=\"{args.namespace}\", container=~\"{container_re}\"}}[2m]))"
            " / "
            f"sum(kube_pod_container_resource_limits{{resource=\"cpu\", namespace=\"{args.namespace}\", container=~\"{container_re}\"}})"
            ") * 100"
        )

        cpu_mcores_queries[svc] = cpu_mcores_q
        replica_queries[svc] = rep_q
        cpu_util_pct_queries[svc] = util_q
        if args.debug:
            sys.stderr.write(f"[QUERY {svc}] cpu_mcores: {cpu_mcores_q}\n")
            sys.stderr.write(f"[QUERY {svc}] replicas:   {rep_q}\n")
            sys.stderr.write(f"[QUERY {svc}] cpu_util%:  {util_q}\n")

    # Query Prometheus
    step = max(args.bucket_sec, 5)
    if not prom_has_data(args.prom, args.namespace, start, end):
        if args.debug:
            sys.stderr.write("No Prometheus series found in the requested time window for namespace; Prom columns will be empty.\n")
    cpu_series = {}
    rep_series = {}
    util_series = {}
    for svc in args.services:
        try:
            cpu_res = prom_query_range(args.prom, cpu_mcores_queries[svc], start, end, step)
        except Exception as e:
            cpu_res = []
            if args.debug:
                sys.stderr.write(f"[ERROR {svc}] cpu_mcores query failed: {e}\n")
        try:
            rep_res = prom_query_range(args.prom, replica_queries[svc], start, end, step)
        except Exception as e:
            rep_res = []
            if args.debug:
                sys.stderr.write(f"[ERROR {svc}] replicas query failed: {e}\n")
        try:
            util_res = prom_query_range(args.prom, cpu_util_pct_queries[svc], start, end, step)
        except Exception as e:
            util_res = []
            if args.debug:
                sys.stderr.write(f"[ERROR {svc}] cpu_util% query failed: {e}\n")
        # Reduce to single time series by summing values at each ts if multiple vectors returned
        def reduce_series(results):
            agg = {}
            for r in results:
                for ts_str, val_str in r.get("values", []):
                    ts = int(float(ts_str))
                    try:
                        v = float(val_str)
                    except Exception:
                        continue
                    agg[ts] = agg.get(ts, 0.0) + v
            return agg
        cpu_series[svc] = reduce_series(cpu_res)
        rep_series[svc] = reduce_series(rep_res)
        util_series[svc] = reduce_series(util_res)
        if args.debug:
            def series_stats(name, d):
                if not d:
                    return "empty"
                keys = sorted(d.keys())
                return f"{len(d)} pts from {keys[0]} to {keys[-1]}"
            sys.stderr.write(f"[SERIES {svc}] cpu_mcores: {series_stats('cpu', cpu_series[svc])}\n")
            sys.stderr.write(f"[SERIES {svc}] replicas:   {series_stats('rep', rep_series[svc])}\n")
            sys.stderr.write(f"[SERIES {svc}] cpu_util%:  {series_stats('util', util_series[svc])}\n")

    # Prepare output
    fieldnames = [
        "time_iso",
        "time_unix",
        "bucket_sec",
        "reqs",
        "fail_pct",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "max_ms",
    ]
    for svc in args.services:
        fieldnames.append(f"{svc}_replicas")
        fieldnames.append(f"{svc}_cpu_mcores")
        fieldnames.append(f"{svc}_cpu_util_pct")

    # Ensure output directory exists
    out_dir = args.out.rsplit("/", 1)[0]
    if out_dir:
        import os
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        populated_rows = 0
        # Helper to select the latest sample at or before a timestamp
        def at_or_before(series_dict, ts):
            if not series_dict:
                return None
            keys = [k for k in series_dict.keys() if k <= ts]
            if not keys:
                return None
            return series_dict[max(keys)]

        for bucket in sorted(per_bucket.keys()):
            data = per_bucket[bucket]
            reqs = data["reqs"]
            fails = data["fails"]
            durations = sorted(data["durations"]) if data["durations"] else []
            row = {
                "time_iso": dt.datetime.utcfromtimestamp(bucket).isoformat() + "Z",
                "time_unix": bucket,
                "bucket_sec": args.bucket_sec,
                "reqs": reqs,
                "fail_pct": (fails / reqs * 100.0) if reqs else 0.0,
                "p50_ms": percentile(durations, 0.5) if durations else None,
                "p90_ms": percentile(durations, 0.9) if durations else None,
                "p95_ms": percentile(durations, 0.95) if durations else None,
                "max_ms": durations[-1] if durations else None,
            }
            # attach infra metrics (nearest timestamp from prom step)
            for svc in args.services:
                rep = rep_series.get(svc, {})
                cpu = cpu_series.get(svc, {})
                util = util_series.get(svc, {})
                rep_val = at_or_before(rep, bucket)
                cpu_val = at_or_before(cpu, bucket)
                util_val = at_or_before(util, bucket)
                row[f"{svc}_replicas"] = rep_val
                row[f"{svc}_cpu_mcores"] = cpu_val
                row[f"{svc}_cpu_util_pct"] = util_val
            if any(row.get(f"{svc}_replicas") is not None or row.get(f"{svc}_cpu_mcores") is not None or row.get(f"{svc}_cpu_util_pct") is not None for svc in args.services):
                populated_rows += 1
            writer.writerow(row)

    if args.debug:
        sys.stderr.write(f"rows written: {len(per_bucket)}; rows with any prom data: {populated_rows}\n")
    print(f"Enhanced report written: {args.out}")


if __name__ == "__main__":
    main()


