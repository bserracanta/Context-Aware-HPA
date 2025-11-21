#!/usr/bin/env python3
"""
k6 Latency Breakdown Comparison Script

Compares two k6 CSV outputs to analyze latency breakdown differences:
- Blocked time comparison
- Connecting time comparison
- Sending time comparison
- Waiting time comparison (server processing)
- Receiving time comparison

This helps identify which HPA configuration or test condition performs better.
"""

import argparse
import csv
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    print("ERROR: Required packages not installed. Install with:")
    print("  pip install pandas numpy matplotlib")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare two k6 CSV files to analyze latency breakdown differences",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare two k6 CSV files
  python3 compare_latency_breakdown.py \\
    --k6-csv1 k6/reports/combo_prop6535_limits4035_hpa1_20251111_192236.csv \\
    --k6-csv2 k6/reports/combo_prop6535_limits4035_hpa2_20251111_192236.csv \\
    --name1 "HPA1" --name2 "HPA2"

  # Compare with time filtering
  python3 compare_latency_breakdown.py \\
    --k6-csv1 k6/reports/hpa1.csv \\
    --k6-csv2 k6/reports/hpa2.csv \\
    --name1 "HPA1" --name2 "HPA2" \\
    --start-time "2025-11-11T19:27:00Z" \\
    --end-time "2025-11-11T19:37:00Z" \\
    --bucket-sec 30

  # Compare with Prometheus correlation
  python3 compare_latency_breakdown.py \\
    --k6-csv1 k6/reports/hpa1.csv \\
    --k6-csv2 k6/reports/hpa2.csv \\
    --name1 "HPA1" --name2 "HPA2" \\
    --prom http://127.0.0.1:9090 \\
    --namespace socialnetwork \\
    --services nginx-thrift compose-post-service text-service user-mention-service
        """
    )
    parser.add_argument("--k6-csv1", required=True, help="Path to first k6 CSV export")
    parser.add_argument("--k6-csv2", required=True, help="Path to second k6 CSV export")
    parser.add_argument("--name1", default="Test1", help="Name for first test (default: Test1)")
    parser.add_argument("--name2", default="Test2", help="Name for second test (default: Test2)")
    parser.add_argument("--bucket-sec", type=int, default=10, 
                       help="Time bucket size in seconds for aggregation (default: 10)")
    parser.add_argument("--prom", help="Prometheus URL for correlating with replicas/CPU")
    parser.add_argument("--namespace", default="socialnetwork", 
                       help="Kubernetes namespace for Prometheus queries")
    parser.add_argument("--services", nargs="+", 
                       default=["nginx-thrift", "compose-post-service", "text-service", "user-mention-service"],
                       help="Service names for Prometheus queries")
    parser.add_argument("--start-time", help="Filter start time (ISO format: 2025-11-11T19:27:00Z)")
    parser.add_argument("--end-time", help="Filter end time (ISO format: 2025-11-11T19:37:00Z)")
    parser.add_argument("--out-dir", default="k6/comparison_output",
                       help="Output directory for plots and reports (default: k6/comparison_output)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    return parser.parse_args()


def read_k6_csv(csv_path, start_time=None, end_time=None, debug=False):
    """Read k6 CSV and extract timing breakdown metrics."""
    
    # Timing metric names
    timing_metrics = [
        "http_req_duration",  # Total duration
        "http_req_blocked",   # Time blocked waiting for connection
        "http_req_connecting",  # TCP connection time
        "http_req_tls_handshaking",  # TLS handshake time
        "http_req_sending",   # Time sending request
        "http_req_waiting",   # Time waiting for response (TTFB + processing)
        "http_req_receiving",  # Time receiving response
    ]
    
    # Parse ISO timestamps if provided
    start_ts = None
    end_ts = None
    if start_time:
        start_ts = int(dt.datetime.fromisoformat(start_time.replace('Z', '+00:00')).timestamp())
    if end_time:
        end_ts = int(dt.datetime.fromisoformat(end_time.replace('Z', '+00:00')).timestamp())
    
    # Process rows sequentially - k6 exports metrics sequentially for each request
    requests = []
    current_request = None
    current_request_timestamp = None
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            metric_name = row.get("metric_name", "")
            timestamp = float(row.get("timestamp", 0))
            
            # Filter by time range if provided
            if start_ts and timestamp < start_ts:
                continue
            if end_ts and timestamp > end_ts:
                continue
            
            # Only process timing metrics
            if metric_name not in timing_metrics:
                continue
            
            # When we see http_req_duration, it's a new request
            if metric_name == "http_req_duration":
                # Close previous request if it exists
                if current_request and "http_req_duration" in current_request:
                    # Initialize missing timing components to 0
                    for metric in timing_metrics:
                        if metric not in current_request:
                            current_request[metric] = 0.0
                    requests.append(current_request)
                
                # Start new request
                url = row.get("name", "") or row.get("url", "")
                method = row.get("method", "")
                current_request = {
                    "timestamp": timestamp,
                    "url": url,
                    "method": method,
                    "status": row.get("error", "") == "" and row.get("error_code", "") == "",
                    "error": row.get("error", ""),
                    "error_code": row.get("error_code", ""),
                    "expected_response": row.get("expected_response", "true").lower() == "true",
                }
                current_request_timestamp = timestamp
                
                # Store duration value
                try:
                    value = float(row.get("metric_value", 0))
                    current_request[metric_name] = value
                except (ValueError, TypeError):
                    current_request[metric_name] = 0.0
            
            # If we have a current request and this is not http_req_duration
            elif current_request:
                # Metrics for the same request have the exact same timestamp
                if timestamp == current_request_timestamp:
                    # Store the metric value
                    try:
                        value = float(row.get("metric_value", 0))
                        current_request[metric_name] = value
                    except (ValueError, TypeError):
                        current_request[metric_name] = 0.0
                # If timestamp differs, we've moved to a new request
                elif timestamp != current_request_timestamp and "http_req_duration" in current_request:
                    # Close current request
                    for metric in timing_metrics:
                        if metric not in current_request:
                            current_request[metric] = 0.0
                    requests.append(current_request)
                    current_request = None
                    current_request_timestamp = None
    
    # Don't forget the last request
    if current_request and "http_req_duration" in current_request:
        # Initialize missing timing components to 0
        for metric in timing_metrics:
            if metric not in current_request:
                current_request[metric] = 0.0
        requests.append(current_request)
    
    # Sort by timestamp
    requests.sort(key=lambda x: x["timestamp"])
    
    if debug:
        print(f"Loaded {len(requests)} complete requests from {csv_path}")
        if requests:
            print(f"Time range: {dt.datetime.fromtimestamp(requests[0]['timestamp'])} to {dt.datetime.fromtimestamp(requests[-1]['timestamp'])}")
    
    return requests


def bucket_requests(requests, bucket_sec=10):
    """Bucket requests by time windows and calculate statistics."""
    
    buckets = defaultdict(lambda: {
        "requests": [],
        "total": 0,
        "failed": 0,
        "durations": [],
        "blocked": [],
        "connecting": [],
        "tls_handshaking": [],
        "sending": [],
        "waiting": [],
        "receiving": [],
    })
    
    for req in requests:
        timestamp = req["timestamp"]
        bucket = int(timestamp - (timestamp % bucket_sec))
        
        buckets[bucket]["requests"].append(req)
        buckets[bucket]["total"] += 1
        if not req.get("status", True) or not req.get("expected_response", True):
            buckets[bucket]["failed"] += 1
        
        # Extract timing components
        if "http_req_duration" in req:
            buckets[bucket]["durations"].append(req["http_req_duration"])
        if "http_req_blocked" in req:
            buckets[bucket]["blocked"].append(req["http_req_blocked"])
        if "http_req_connecting" in req:
            buckets[bucket]["connecting"].append(req["http_req_connecting"])
        if "http_req_tls_handshaking" in req:
            buckets[bucket]["tls_handshaking"].append(req["http_req_tls_handshaking"])
        if "http_req_sending" in req:
            buckets[bucket]["sending"].append(req["http_req_sending"])
        if "http_req_waiting" in req:
            buckets[bucket]["waiting"].append(req["http_req_waiting"])
        if "http_req_receiving" in req:
            buckets[bucket]["receiving"].append(req["http_req_receiving"])
    
    # Calculate statistics per bucket
    bucket_stats = []
    for bucket_ts in sorted(buckets.keys()):
        bucket = buckets[bucket_ts]
        stats = {
            "timestamp": bucket_ts,
            "time_iso": dt.datetime.utcfromtimestamp(bucket_ts).isoformat() + "Z",
            "total_requests": bucket["total"],
            "failed_requests": bucket["failed"],
            "success_rate": (1 - bucket["failed"] / bucket["total"]) * 100 if bucket["total"] > 0 else 0,
            "req_per_sec": bucket["total"] / bucket_sec if bucket_sec > 0 else 0,
        }
        
        # Calculate percentiles for each timing component
        def calc_percentiles(values, percentiles=[50, 90, 95, 99]):
            if not values:
                return {f"p{p}": 0.0 for p in percentiles}
            sorted_vals = sorted(values)
            result = {}
            for p in percentiles:
                idx = int((p / 100) * (len(sorted_vals) - 1))
                result[f"p{p}"] = sorted_vals[idx] if idx < len(sorted_vals) else sorted_vals[-1]
            result["avg"] = sum(sorted_vals) / len(sorted_vals)
            result["min"] = sorted_vals[0]
            result["max"] = sorted_vals[-1]
            return result
        
        stats["duration"] = calc_percentiles(bucket["durations"])
        stats["blocked"] = calc_percentiles(bucket["blocked"])
        stats["connecting"] = calc_percentiles(bucket["connecting"])
        stats["tls_handshaking"] = calc_percentiles(bucket["tls_handshaking"])
        stats["sending"] = calc_percentiles(bucket["sending"])
        stats["waiting"] = calc_percentiles(bucket["waiting"])
        stats["receiving"] = calc_percentiles(bucket["receiving"])
        
        bucket_stats.append(stats)
    
    return bucket_stats


def query_prometheus_replicas(prom_url, namespace, services, start_ts, end_ts, bucket_sec=10, debug=False):
    """Query Prometheus for replica counts per service."""
    import urllib.parse
    import urllib.request
    import json
    
    replica_data = {service: {} for service in services}
    
    if not prom_url:
        return replica_data
    
    # Query for replica counts
    for service in services:
        # Map service name to deployment name (remove -service suffix if present)
        deploy_name = service
        if service.endswith("-service"):
            pod_prefix = service[:-8]
        else:
            pod_prefix = service
        
        # Query kube_deployment_status_replicas
        query = f'kube_deployment_status_replicas{{namespace="{namespace}",deployment="{deploy_name}"}}'
        
        params = {
            "query": query,
            "start": str(start_ts),
            "end": str(end_ts),
            "step": str(bucket_sec),
        }
        
        url = f"{prom_url.rstrip('/')}/api/v1/query_range?{urllib.parse.urlencode(params)}"
        
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            
            if payload.get("status") == "success":
                results = payload.get("data", {}).get("result", [])
                for result in results:
                    values = result.get("values", [])
                    for ts_str, val_str in values:
                        ts = int(float(ts_str))
                        val = float(val_str)
                        # Align to bucket
                        bucket_ts = ts - (ts % bucket_sec)
                        replica_data[service][bucket_ts] = val
        except Exception as e:
            if debug:
                print(f"Warning: Failed to query Prometheus for {service}: {e}")
    
    return replica_data


def create_comparison_visualizations(bucket_stats1, bucket_stats2, name1, name2, replica_data=None, out_dir="k6/comparison_output"):
    """Create comparison visualization plots for latency breakdown."""
    
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    
    # Prepare data for plotting
    timestamps1 = [s["timestamp"] for s in bucket_stats1]
    times1 = [dt.datetime.utcfromtimestamp(ts) for ts in timestamps1]
    timestamps2 = [s["timestamp"] for s in bucket_stats2]
    times2 = [dt.datetime.utcfromtimestamp(ts) for ts in timestamps2]
    
    # Extract timing components for test 1
    duration_avg1 = [s["duration"]["avg"] for s in bucket_stats1]
    blocked_avg1 = [s["blocked"]["avg"] for s in bucket_stats1]
    connecting_avg1 = [s["connecting"]["avg"] for s in bucket_stats1]
    sending_avg1 = [s["sending"]["avg"] for s in bucket_stats1]
    waiting_avg1 = [s["waiting"]["avg"] for s in bucket_stats1]
    receiving_avg1 = [s["receiving"]["avg"] for s in bucket_stats1]
    
    # Extract timing components for test 2
    duration_avg2 = [s["duration"]["avg"] for s in bucket_stats2]
    blocked_avg2 = [s["blocked"]["avg"] for s in bucket_stats2]
    connecting_avg2 = [s["connecting"]["avg"] for s in bucket_stats2]
    sending_avg2 = [s["sending"]["avg"] for s in bucket_stats2]
    waiting_avg2 = [s["waiting"]["avg"] for s in bucket_stats2]
    receiving_avg2 = [s["receiving"]["avg"] for s in bucket_stats2]
    
    # Create comparison plots
    fig, axes = plt.subplots(3, 1, figsize=(16, 12))
    
    # Plot 1: Total Duration Comparison
    ax1 = axes[0]
    ax1.plot(times1, duration_avg1, label=f"{name1} - Total Duration", linewidth=2, color="#FF6B6B", linestyle="-")
    ax1.plot(times2, duration_avg2, label=f"{name2} - Total Duration", linewidth=2, color="#4ECDC4", linestyle="-")
    ax1.plot(times1, waiting_avg1, label=f"{name1} - Waiting (Server)", linewidth=2, color="#FFA07A", linestyle="--")
    ax1.plot(times2, waiting_avg2, label=f"{name2} - Waiting (Server)", linewidth=2, color="#98D8C8", linestyle="--")
    
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title("Total Duration and Waiting Time Comparison")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
    
    # Plot 2: Waiting Time Comparison (most important)
    ax2 = axes[1]
    ax2.plot(times1, waiting_avg1, label=f"{name1} - Waiting (Server Processing)", linewidth=2.5, color="#FF6B6B")
    ax2.plot(times2, waiting_avg2, label=f"{name2} - Waiting (Server Processing)", linewidth=2.5, color="#4ECDC4")
    ax2.fill_between(times1, waiting_avg1, alpha=0.3, color="#FF6B6B")
    ax2.fill_between(times2, waiting_avg2, alpha=0.3, color="#4ECDC4")
    
    ax2.set_xlabel("Time")
    ax2.set_ylabel("Waiting Time (ms)")
    ax2.set_title("Server Processing Time Comparison (Waiting Phase)")
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
    
    # Plot 3: All Components Comparison
    ax3 = axes[2]
    ax3.plot(times1, waiting_avg1, label=f"{name1} - Waiting", linewidth=2, color="#FF6B6B")
    ax3.plot(times2, waiting_avg2, label=f"{name2} - Waiting", linewidth=2, color="#4ECDC4")
    ax3.plot(times1, blocked_avg1, label=f"{name1} - Blocked", linewidth=1.5, color="#FFA07A", alpha=0.7)
    ax3.plot(times2, blocked_avg2, label=f"{name2} - Blocked", linewidth=1.5, color="#98D8C8", alpha=0.7)
    ax3.plot(times1, connecting_avg1, label=f"{name1} - Connecting", linewidth=1.5, color="#FFD700", alpha=0.7)
    ax3.plot(times2, connecting_avg2, label=f"{name2} - Connecting", linewidth=1.5, color="#87CEEB", alpha=0.7)
    ax3.plot(times1, sending_avg1, label=f"{name1} - Sending", linewidth=1.5, color="#FF69B4", alpha=0.7)
    ax3.plot(times2, sending_avg2, label=f"{name2} - Sending", linewidth=1.5, color="#20B2AA", alpha=0.7)
    ax3.plot(times1, receiving_avg1, label=f"{name1} - Receiving", linewidth=1.5, color="#FF1493", alpha=0.7)
    ax3.plot(times2, receiving_avg2, label=f"{name2} - Receiving", linewidth=1.5, color="#00CED1", alpha=0.7)
    
    ax3.set_xlabel("Time")
    ax3.set_ylabel("Latency (ms)")
    ax3.set_title("All Latency Components Comparison")
    ax3.legend(loc="upper left", ncol=2, fontsize=8)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha="right")
    
    plt.tight_layout()
    plot_path = f"{out_dir}/latency_comparison.png"
    plt.savefig(plot_path, dpi=300, bbox_inches="tight")
    print(f"Saved comparison plot: {plot_path}")
    plt.close()
    
    # Create side-by-side comparison of waiting times
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Test 1 waiting time
    ax1.plot(times1, waiting_avg1, label="Waiting (Server)", linewidth=2.5, color="#FF6B6B")
    ax1.fill_between(times1, waiting_avg1, alpha=0.3, color="#FF6B6B")
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Waiting Time (ms)")
    ax1.set_title(f"{name1} - Server Processing Time")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
    
    # Test 2 waiting time
    ax2.plot(times2, waiting_avg2, label="Waiting (Server)", linewidth=2.5, color="#4ECDC4")
    ax2.fill_between(times2, waiting_avg2, alpha=0.3, color="#4ECDC4")
    ax2.set_xlabel("Time")
    ax2.set_ylabel("Waiting Time (ms)")
    ax2.set_title(f"{name2} - Server Processing Time")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
    
    plt.tight_layout()
    plot_path = f"{out_dir}/waiting_time_comparison.png"
    plt.savefig(plot_path, dpi=300, bbox_inches="tight")
    print(f"Saved waiting time comparison: {plot_path}")
    plt.close()


def print_comparison_summary(bucket_stats1, bucket_stats2, name1, name2):
    """Print comparison summary statistics."""
    
    print("\n" + "="*80)
    print("LATENCY BREAKDOWN COMPARISON")
    print("="*80)
    
    # Calculate overall statistics for both tests
    def calc_overall_stats(bucket_stats):
        all_durations = []
        all_blocked = []
        all_connecting = []
        all_sending = []
        all_waiting = []
        all_receiving = []
        total_requests = 0
        total_failed = 0
        
        for stats in bucket_stats:
            all_durations.extend([d for d in [stats["duration"]["avg"]] if d > 0])
            all_blocked.extend([b for b in [stats["blocked"]["avg"]] if b > 0])
            all_connecting.extend([c for c in [stats["connecting"]["avg"]] if c > 0])
            all_sending.extend([s for s in [stats["sending"]["avg"]] if s > 0])
            all_waiting.extend([w for w in [stats["waiting"]["avg"]] if w > 0])
            all_receiving.extend([r for r in [stats["receiving"]["avg"]] if r > 0])
            total_requests += stats["total_requests"]
            total_failed += stats["failed_requests"]
        
        def calc_stats(values):
            if not values:
                return {"avg": 0, "min": 0, "max": 0, "p50": 0, "p95": 0, "p99": 0}
            sorted_vals = sorted(values)
            return {
                "avg": sum(values) / len(values),
                "min": sorted_vals[0],
                "max": sorted_vals[-1],
                "p50": sorted_vals[int(0.5 * len(sorted_vals))],
                "p95": sorted_vals[int(0.95 * len(sorted_vals))],
                "p99": sorted_vals[int(0.99 * len(sorted_vals))] if len(sorted_vals) > 1 else sorted_vals[0],
            }
        
        return {
            "duration": calc_stats(all_durations),
            "blocked": calc_stats(all_blocked),
            "connecting": calc_stats(all_connecting),
            "sending": calc_stats(all_sending),
            "waiting": calc_stats(all_waiting),
            "receiving": calc_stats(all_receiving),
            "total_requests": total_requests,
            "total_failed": total_failed,
            "success_rate": (1 - total_failed / total_requests) * 100 if total_requests > 0 else 0,
        }
    
    stats1 = calc_overall_stats(bucket_stats1)
    stats2 = calc_overall_stats(bucket_stats2)
    
    print(f"\n{'Metric':<25} {name1:<20} {name2:<20} {'Difference':<15} {'% Change':<15}")
    print("-"*95)
    
    def print_metric(metric_name, stat1, stat2):
        diff = stat2["avg"] - stat1["avg"]
        pct_change = (diff / stat1["avg"] * 100) if stat1["avg"] > 0 else 0
        print(f"{metric_name:<25} {stat1['avg']:>18.2f} ms {stat2['avg']:>18.2f} ms {diff:>13.2f} ms {pct_change:>13.1f}%")
    
    print("\n📊 OVERALL STATISTICS:")
    print_metric("Total Duration", stats1["duration"], stats2["duration"])
    print_metric("Waiting (Server)", stats1["waiting"], stats2["waiting"])
    print_metric("Blocked", stats1["blocked"], stats2["blocked"])
    print_metric("Connecting", stats1["connecting"], stats2["connecting"])
    print_metric("Sending", stats1["sending"], stats2["sending"])
    print_metric("Receiving", stats1["receiving"], stats2["receiving"])
    
    print(f"\n📈 REQUEST STATISTICS:")
    print(f"{'Metric':<25} {name1:<20} {name2:<20} {'Difference':<15}")
    print("-"*80)
    print(f"{'Total Requests':<25} {stats1['total_requests']:<20} {stats2['total_requests']:<20} {stats2['total_requests'] - stats1['total_requests']:<15}")
    print(f"{'Failed Requests':<25} {stats1['total_failed']:<20} {stats2['total_failed']:<20} {stats2['total_failed'] - stats1['total_failed']:<15}")
    print(f"{'Success Rate (%)':<25} {stats1['success_rate']:<20.2f} {stats2['success_rate']:<20.2f} {stats2['success_rate'] - stats1['success_rate']:<15.2f}")
    
    print(f"\n🔍 KEY INSIGHTS:")
    
    # Compare waiting times
    waiting_diff = stats2["waiting"]["avg"] - stats1["waiting"]["avg"]
    waiting_pct = (waiting_diff / stats1["waiting"]["avg"] * 100) if stats1["waiting"]["avg"] > 0 else 0
    
    if waiting_pct < -5:
        print(f"✅ {name2} has {abs(waiting_pct):.1f}% LOWER waiting time than {name1}")
        print(f"   → {name2} performs better for server-side processing")
    elif waiting_pct > 5:
        print(f"❌ {name2} has {waiting_pct:.1f}% HIGHER waiting time than {name1}")
        print(f"   → {name1} performs better for server-side processing")
    else:
        print(f"⚖️  Waiting times are similar ({waiting_pct:.1f}% difference)")
    
    # Compare total duration
    duration_diff = stats2["duration"]["avg"] - stats1["duration"]["avg"]
    duration_pct = (duration_diff / stats1["duration"]["avg"] * 100) if stats1["duration"]["avg"] > 0 else 0
    
    if duration_pct < -5:
        print(f"✅ {name2} has {abs(duration_pct):.1f}% LOWER total latency than {name1}")
    elif duration_pct > 5:
        print(f"❌ {name2} has {duration_pct:.1f}% HIGHER total latency than {name1}")
    else:
        print(f"⚖️  Total latencies are similar ({duration_pct:.1f}% difference)")
    
    # Compare success rates
    success_diff = stats2["success_rate"] - stats1["success_rate"]
    if success_diff > 1:
        print(f"✅ {name2} has {success_diff:.1f}% HIGHER success rate than {name1}")
    elif success_diff < -1:
        print(f"❌ {name2} has {abs(success_diff):.1f}% LOWER success rate than {name1}")
    else:
        print(f"⚖️  Success rates are similar ({success_diff:.1f}% difference)")
    
    print(f"\n💡 RECOMMENDATIONS:")
    
    if waiting_pct < -10:
        print(f"  → {name2} is significantly faster - consider using this configuration")
    elif waiting_pct > 10:
        print(f"  → {name1} is significantly faster - consider using this configuration")
    else:
        print(f"  → Both configurations perform similarly - choose based on other factors")
    
    if stats1["waiting"]["avg"] > 1000 or stats2["waiting"]["avg"] > 1000:
        print(f"  → High waiting times (>1s) indicate server-side processing bottleneck")
        print(f"  → Consider: scaling up replicas, optimizing application code, checking database performance")
    
    print()


def export_comparison_report(bucket_stats1, bucket_stats2, name1, name2, replica_data=None, out_dir="k6/comparison_output"):
    """Export comparison CSV report."""
    
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    
    csv_path = f"{out_dir}/latency_comparison_detailed.csv"
    
    # Determine common timestamps
    timestamps1 = {s["timestamp"] for s in bucket_stats1}
    timestamps2 = {s["timestamp"] for s in bucket_stats2}
    common_timestamps = sorted(timestamps1.intersection(timestamps2))
    
    # Create lookup dictionaries
    stats1_dict = {s["timestamp"]: s for s in bucket_stats1}
    stats2_dict = {s["timestamp"]: s for s in bucket_stats2}
    
    with open(csv_path, 'w', newline='') as f:
        fieldnames = [
            "timestamp", "time_iso",
            f"{name1}_total_requests", f"{name1}_failed_requests", f"{name1}_success_rate", f"{name1}_req_per_sec",
            f"{name1}_duration_avg", f"{name1}_waiting_avg", f"{name1}_blocked_avg", f"{name1}_connecting_avg",
            f"{name1}_sending_avg", f"{name1}_receiving_avg",
            f"{name2}_total_requests", f"{name2}_failed_requests", f"{name2}_success_rate", f"{name2}_req_per_sec",
            f"{name2}_duration_avg", f"{name2}_waiting_avg", f"{name2}_blocked_avg", f"{name2}_connecting_avg",
            f"{name2}_sending_avg", f"{name2}_receiving_avg",
            "waiting_diff", "waiting_pct_change", "duration_diff", "duration_pct_change",
        ]
        
        # Add replica columns if available
        if replica_data:
            for service in replica_data.keys():
                fieldnames.append(f"{service}_replicas")
        
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for ts in common_timestamps:
            if ts not in stats1_dict or ts not in stats2_dict:
                continue
            
            s1 = stats1_dict[ts]
            s2 = stats2_dict[ts]
            
            waiting_diff = s2["waiting"]["avg"] - s1["waiting"]["avg"]
            waiting_pct = (waiting_diff / s1["waiting"]["avg"] * 100) if s1["waiting"]["avg"] > 0 else 0
            duration_diff = s2["duration"]["avg"] - s1["duration"]["avg"]
            duration_pct = (duration_diff / s1["duration"]["avg"] * 100) if s1["duration"]["avg"] > 0 else 0
            
            row = {
                "timestamp": ts,
                "time_iso": s1["time_iso"],
                f"{name1}_total_requests": s1["total_requests"],
                f"{name1}_failed_requests": s1["failed_requests"],
                f"{name1}_success_rate": s1["success_rate"],
                f"{name1}_req_per_sec": s1["req_per_sec"],
                f"{name1}_duration_avg": s1["duration"]["avg"],
                f"{name1}_waiting_avg": s1["waiting"]["avg"],
                f"{name1}_blocked_avg": s1["blocked"]["avg"],
                f"{name1}_connecting_avg": s1["connecting"]["avg"],
                f"{name1}_sending_avg": s1["sending"]["avg"],
                f"{name1}_receiving_avg": s1["receiving"]["avg"],
                f"{name2}_total_requests": s2["total_requests"],
                f"{name2}_failed_requests": s2["failed_requests"],
                f"{name2}_success_rate": s2["success_rate"],
                f"{name2}_req_per_sec": s2["req_per_sec"],
                f"{name2}_duration_avg": s2["duration"]["avg"],
                f"{name2}_waiting_avg": s2["waiting"]["avg"],
                f"{name2}_blocked_avg": s2["blocked"]["avg"],
                f"{name2}_connecting_avg": s2["connecting"]["avg"],
                f"{name2}_sending_avg": s2["sending"]["avg"],
                f"{name2}_receiving_avg": s2["receiving"]["avg"],
                "waiting_diff": waiting_diff,
                "waiting_pct_change": waiting_pct,
                "duration_diff": duration_diff,
                "duration_pct_change": duration_pct,
            }
            
            # Add replica data
            if replica_data:
                for service in replica_data.keys():
                    replica_val = replica_data[service].get(ts, None)
                    row[f"{service}_replicas"] = replica_val if replica_val is not None else ""
            
            writer.writerow(row)
    
    print(f"Exported comparison report: {csv_path}")


def main():
    args = parse_args()
    
    print("="*80)
    print("k6 Latency Breakdown Comparison Tool")
    print("="*80)
    print(f"Test 1: {args.name1}")
    print(f"  CSV: {args.k6_csv1}")
    print(f"Test 2: {args.name2}")
    print(f"  CSV: {args.k6_csv2}")
    print(f"Bucket size: {args.bucket_sec} seconds")
    if args.start_time:
        print(f"Start time filter: {args.start_time}")
    if args.end_time:
        print(f"End time filter: {args.end_time}")
    if args.prom:
        print(f"Prometheus URL: {args.prom}")
        print(f"Services: {', '.join(args.services)}")
    print(f"Output directory: {args.out_dir}")
    print("="*80)
    
    # Read k6 CSV files
    print(f"\n📖 Reading k6 CSV files...")
    requests1 = read_k6_csv(args.k6_csv1, args.start_time, args.end_time, args.debug)
    requests2 = read_k6_csv(args.k6_csv2, args.start_time, args.end_time, args.debug)
    
    if not requests1:
        print(f"ERROR: No requests found in {args.k6_csv1}")
        sys.exit(1)
    if not requests2:
        print(f"ERROR: No requests found in {args.k6_csv2}")
        sys.exit(1)
    
    # Bucket requests
    print(f"📊 Bucketing requests into {args.bucket_sec}-second windows...")
    bucket_stats1 = bucket_requests(requests1, args.bucket_sec)
    bucket_stats2 = bucket_requests(requests2, args.bucket_sec)
    
    # Query Prometheus for replicas if URL provided
    replica_data = None
    if args.prom and bucket_stats1 and bucket_stats2:
        print("🔍 Querying Prometheus for replica counts...")
        start_ts = min(bucket_stats1[0]["timestamp"], bucket_stats2[0]["timestamp"])
        end_ts = max(bucket_stats1[-1]["timestamp"], bucket_stats2[-1]["timestamp"]) + args.bucket_sec
        replica_data = query_prometheus_replicas(
            args.prom, args.namespace, args.services, 
            start_ts, end_ts, args.bucket_sec, args.debug
        )
    
    # Print comparison summary
    print_comparison_summary(bucket_stats1, bucket_stats2, args.name1, args.name2)
    
    # Create visualizations
    print("📈 Creating comparison visualizations...")
    create_comparison_visualizations(bucket_stats1, bucket_stats2, args.name1, args.name2, replica_data, args.out_dir)
    
    # Export detailed report
    print("💾 Exporting detailed comparison CSV report...")
    export_comparison_report(bucket_stats1, bucket_stats2, args.name1, args.name2, replica_data, args.out_dir)
    
    print("\n✅ Comparison complete!")
    print(f"📁 Output files saved to: {args.out_dir}/")


if __name__ == "__main__":
    main()

