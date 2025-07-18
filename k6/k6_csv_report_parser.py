import pandas as pd
import matplotlib.pyplot as plt
from collections import defaultdict

# Read the CSV files
csv_file_1 = 'reports/deathstar_base.csv'

data_1 = pd.read_csv(csv_file_1, low_memory=False)

# Extract the http_req_duration values from rows where the first column starts with 'http_req_duration'
http_req_duration_1 = data_1[data_1.iloc[:, 0].str.startswith('http_req_duration')].iloc[:, [1, 2]].apply(tuple, axis=1).tolist()

# Separate the timestamps and latency values
timestamps_1, latencies_1 = zip(*http_req_duration_1)

# Normalize so that the initial timestamp is 0 in milliseconds  
# Store the original first timestamps in Unix format
original_timestamps_1 = [float(ts) for ts in timestamps_1]
timestamps_1 = [float(ts) - float(timestamps_1[0]) for ts in timestamps_1]
latencies_1 = [float(lat) for lat in latencies_1]

# Keep only timestamps smaller than 1100 and their corresponding latency values
timestamps_1, latencies_1 = zip(*[(ts, lat) for ts, lat in zip(timestamps_1, latencies_1) if ts < 1100])

### AVERAGE LATENCY PLOTTING ###

# Create a function to process buckets and compute averages
def process_buckets(timestamps, latencies, bin_width):
    buckets = defaultdict(list)
    for ts, lat in zip(timestamps, latencies):
        buckets[int(ts // bin_width)].append(lat)
    averaged_latencies = [sum(bucket) / len(bucket) for bucket in buckets.values()]
    time_bins = [bin_index * bin_width for bin_index in sorted(buckets.keys())]
    return buckets, averaged_latencies, time_bins

# Bin width in seconds
bin_width = 3

# Process each dataset
buckets_1, averaged_latencies_1, time_bins_1 = process_buckets(timestamps_1, latencies_1, bin_width)

# Plot average latency over time
plt.figure(figsize=(10, 5))
plt.plot(time_bins_1, averaged_latencies_1, linestyle='-', label='Optimal')
plt.xlabel('Time (ms)')
plt.ylabel('Average Latency (ms)')
plt.title(f'Latency averaged every {bin_width}s')
plt.legend()
plt.grid(True)
plt.tight_layout()

# Print the average latency for each dataset    
def calculate_overall_avg_latency(buckets):
    total_latency = sum(sum(bucket) for bucket in buckets.values())
    total_count = sum(len(bucket) for bucket in buckets.values())
    return total_latency / total_count if total_count > 0 else 0

overall_avg_latency_1 = calculate_overall_avg_latency(buckets_1)

print(f'Average Latency for Optimal: {overall_avg_latency_1:.2f} s')


### TAIL LATENCY PLOTTING ###

# Plot the tail latency (95th percentile) for each of the datasets
tail_latency_1 = [sorted(bucket)[int(0.95 * len(bucket))] for bucket in buckets_1.values() if len(bucket) > 0]

plt.figure(figsize=(10, 5))
plt.plot(time_bins_1[:len(tail_latency_1)], tail_latency_1, linestyle='--', label='Optimal (95th Percentile)')
plt.xlabel('Time (ms)')
plt.ylabel('Tail Latency (ms)')
plt.title(f'Tail Latency (95th Percentile) averaged every {bin_width}s')
plt.legend()
plt.grid(True)
plt.tight_layout()


# Print the overall tail latency for each dataset
def calculate_overall_tail_latency(buckets):
    all_latencies = [lat for bucket in buckets.values() for lat in bucket]
    return sorted(all_latencies)[int(0.95 * len(all_latencies))]

overall_tail_latency_1 = calculate_overall_tail_latency(buckets_1)

print(f'Tail Latency (95th Percentile) for Optimal: {overall_tail_latency_1:.2f} s')


plt.show()