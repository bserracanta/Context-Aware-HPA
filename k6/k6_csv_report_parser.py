import pandas as pd
import matplotlib.pyplot as plt
from collections import defaultdict

# Read the CSV files
csv_file_1 = 'reports/deathstar_base.csv'
#csv_file_2 = '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/base_chainer_results/report_base_chainer_1 copy.csv'
#csv_file_3 = '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/mod_perfect_experiment/report_mod_chainer_3 copy.csv'

data_1 = pd.read_csv(csv_file_1, low_memory=False)
#data_2 = pd.read_csv(csv_file_2, low_memory=False)
#data_3 = pd.read_csv(csv_file_3, low_memory=False)

# Extract the http_req_duration values from rows where the first column starts with 'http_req_duration'
http_req_duration_1 = data_1[data_1.iloc[:, 0].str.startswith('http_req_duration')].iloc[:, [1, 2]].apply(tuple, axis=1).tolist()
# http_req_duration_2 = data_2[data_2.iloc[:, 0].str.startswith('http_req_duration')].iloc[:, [1, 2]].apply(tuple, axis=1).tolist()
# http_req_duration_3 = data_3[data_3.iloc[:, 0].str.startswith('http_req_duration')].iloc[:, [1, 2]].apply(tuple, axis=1).tolist()

# Separate the timestamps and latency values
timestamps_1, latencies_1 = zip(*http_req_duration_1)
# timestamps_2, latencies_2 = zip(*http_req_duration_2)
# timestamps_3, latencies_3 = zip(*http_req_duration_3)

# Normalize so that the initial timestamp is 0 in milliseconds  
# Store the original first timestamps in Unix format
original_timestamps_1 = [float(ts) for ts in timestamps_1]
# original_timestamps_2 = [float(ts) for ts in timestamps_2]
# original_timestamps_3 = [float(ts) for ts in timestamps_3]
timestamps_1 = [float(ts) - float(timestamps_1[0]) for ts in timestamps_1]
# timestamps_2 = [float(ts) - float(timestamps_2[0]) for ts in timestamps_2]
# timestamps_3 = [float(ts) - float(timestamps_3[0]) for ts in timestamps_3]
latencies_1 = [float(lat) for lat in latencies_1]
# latencies_2 = [float(lat) for lat in latencies_2]
# latencies_3 = [float(lat) for lat in latencies_3]

# Keep only timestamps smaller than 1100 and their corresponding latency values
timestamps_1, latencies_1 = zip(*[(ts, lat) for ts, lat in zip(timestamps_1, latencies_1) if ts < 1100])
# timestamps_2, latencies_2 = zip(*[(ts, lat) for ts, lat in zip(timestamps_2, latencies_2) if ts < 1100])
# timestamps_3, latencies_3 = zip(*[(ts, lat) for ts, lat in zip(timestamps_3, latencies_3) if ts < 1100])

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
# buckets_2, averaged_latencies_2, time_bins_2 = process_buckets(timestamps_2, latencies_2, bin_width)
# buckets_3, averaged_latencies_3, time_bins_3 = process_buckets(timestamps_3, latencies_3, bin_width)

# `time_bins_*` holds the start time of each bin for each dataset
# `averaged_latencies_*` holds the average latency in that bin for each dataset
plt.figure(figsize=(10, 5))
plt.plot(time_bins_1, averaged_latencies_1, linestyle='-', label='Optimal')
# plt.plot(time_bins_2, averaged_latencies_2, linestyle='-', label='Default HPA')
# plt.plot(time_bins_3, averaged_latencies_3, linestyle='-', label='Context-Aware HPA')
plt.xlabel('Time (ms)')
plt.ylabel('Average Latency (ms)')
plt.title(f'Latency averaged every {bin_width}s')
plt.legend()
plt.grid(True)
plt.tight_layout()
#plt.show()

# Print the average latency for each dataset    
def calculate_overall_avg_latency(buckets):
    total_latency = sum(sum(bucket) for bucket in buckets.values())
    total_count = sum(len(bucket) for bucket in buckets.values())
    return total_latency / total_count if total_count > 0 else 0

overall_avg_latency_1 = calculate_overall_avg_latency(buckets_1)
# overall_avg_latency_2 = calculate_overall_avg_latency(buckets_2)
# overall_avg_latency_3 = calculate_overall_avg_latency(buckets_3)

print(f'Average Latency for Optimal: {overall_avg_latency_1:.2f} s')
# print(f'Average Latency for Default HPA: {overall_avg_latency_2:.2f} s')
# print(f'Average Latency for Context-Aware HPA: {overall_avg_latency_3:.2f} s')


### TAIL LATENCY PLOTTING ###

# Plot the tail latency (95th percentile) for each of the datasets
tail_latency_1 = [sorted(bucket)[int(0.95 * len(bucket))] for bucket in buckets_1.values() if len(bucket) > 0]
# tail_latency_2 = [sorted(bucket)[int(0.95 * len(bucket))] for bucket in buckets_2.values() if len(bucket) > 0]
# tail_latency_3 = [sorted(bucket)[int(0.95 * len(bucket))] for bucket in buckets_3.values() if len(bucket) > 0]

plt.figure(figsize=(10, 5))
plt.plot(time_bins_1[:len(tail_latency_1)], tail_latency_1, linestyle='--', label='Optimal (95th Percentile)')
# plt.plot(time_bins_2[:len(tail_latency_2)], tail_latency_2, linestyle='--', label='Default HPA (95th Percentile)')
# plt.plot(time_bins_3[:len(tail_latency_3)], tail_latency_3, linestyle='--', label='Context-Aware HPA (95th Percentile)')
plt.xlabel('Time (ms)')
plt.ylabel('Tail Latency (ms)')
plt.title(f'Tail Latency (95th Percentile) averaged every {bin_width}s')
plt.legend()
plt.grid(True)
plt.tight_layout()
#plt.show()


# Print the overall tail latency for each dataset
def calculate_overall_tail_latency(buckets):
    all_latencies = [lat for bucket in buckets.values() for lat in bucket]
    return sorted(all_latencies)[int(0.95 * len(all_latencies))]

overall_tail_latency_1 = calculate_overall_tail_latency(buckets_1)
# overall_tail_latency_2 = calculate_overall_tail_latency(buckets_2)
# overall_tail_latency_3 = calculate_overall_tail_latency(buckets_3)

print(f'Tail Latency (95th Percentile) for Optimal: {overall_tail_latency_1:.2f} s')
# print(f'Tail Latency (95th Percentile) for Default HPA: {overall_tail_latency_2:.2f} s')
# print(f'Tail Latency (95th Percentile) for Context-Aware HPA: {overall_tail_latency_3:.2f} s')



# ### TAIL LATENCY VS REPLICAS UP PLOTTING ###


# # Find the time until replicas are up for each dataset
# # Load the replicas deployment data for dataset 1
# replicas_files = [
#     '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/optimal_chainer_results/Replicas by microservice-data-as-joinbyfield-2025-05-06 15_37_11.csv',
#     '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/base_chainer_results/Replicas by microservice-data-as-joinbyfield-2025-05-05 12_51_42.csv',
#     '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/mod_perfect_experiment/Replicas by microservice-data-as-joinbyfield-2025-05-05 18_06_37.csv'
# ]

# original_timestamps = [original_timestamps_1, original_timestamps_2, original_timestamps_3]

# # Function to process replicas data for a dataset
# def process_replicas_data(file_path):
#     replicas_data = pd.read_csv(file_path, skiprows=1)
#     replicas_data.columns = replicas_data.columns.str.replace('""', '"', regex=False).str.strip()
#     replicas_data.rename(columns={
#         'Time': 'timestamp',
#         'count(kube_pod_info{pod=~"chain-1.*"}) by (app)': 'chain-1',
#         'count(kube_pod_info{pod=~"chain-2.*"}) by (app)': 'chain-2',
#         'count(kube_pod_info{pod=~"chain-3.*"}) by (app)': 'chain-3'
#     }, inplace=True)
#     last_replica_increase = replicas_data.loc[
#         (replicas_data['chain-1'].diff() > 0) | 
#         (replicas_data['chain-2'].diff() > 0) | 
#         (replicas_data['chain-3'].diff() > 0), 
#         'timestamp'
#     ].max()
#     return last_replica_increase / 1000  # Convert to seconds

# # Process each dataset and calculate the time until replicas are up
# time_until_replicas_up = [
#     float(process_replicas_data(file)) - float(original_timestamps[i][0])
#     for i, file in enumerate(replicas_files)
# ]
# time_until_replicas_up[0] = 0 # Remove offset for optimal dataset

# print(f'Time until replicas are up for Optimal: {time_until_replicas_up[0]:.2f} s')
# print(f'Time until replicas are up for Default HPA: {time_until_replicas_up[1]:.2f} s')
# print(f'Time until replicas are up for Context-Aware HPA: {time_until_replicas_up[2]:.2f} s')

# # Plot overall tail latency vs time until replicas are up
# plt.figure(figsize=(8, 5))

# # Data for the plot
# overall_tail_latencies = [overall_tail_latency_1, overall_tail_latency_2, overall_tail_latency_3]
# labels = ['Optimal', 'Default HPA', 'Context-Aware HPA']

# # Sort the data by time until replicas are up
# sorted_data = sorted(zip(time_until_replicas_up, overall_tail_latencies, labels))
# sorted_time_until_replicas_up, sorted_overall_tail_latencies, sorted_labels = zip(*sorted_data)

# # Scatter plot
# plt.scatter(sorted_time_until_replicas_up, sorted_overall_tail_latencies, color=['blue', 'orange', 'green'], s=100)

# # Annotate points with labels
# for i, label in enumerate(sorted_labels):
#     plt.annotate(label, (sorted_time_until_replicas_up[i], sorted_overall_tail_latencies[i]), textcoords="offset points", xytext=(5, 5), ha='center')

# # Connect points with a line
# plt.plot(sorted_time_until_replicas_up, sorted_overall_tail_latencies, linestyle='-', color='gray', alpha=0.7)

# plt.xlabel('Time Until Replicas Are Up (s)')
# plt.ylabel('Overall Tail Latency (95th Percentile) (ms)')
# plt.title('Overall Tail Latency vs Time Until Replicas Are Up')
# plt.grid(True)
# plt.tight_layout()


# ### TRAFFIC RATE AND REPLICAS UP PLOTTING ###
# http_success_file_1 = '/Users/Berta/Documents/Universitat/PhD/HPA_shared_info/k6/optimal_chainer_results/HTTP Request Success Rate-data-as-joinbyfield-2025-05-06 15_37_33.csv'
# http_success_data_1 = pd.read_csv(http_success_file_1, skiprows=1)

# http_success_data_1.columns = http_success_data_1.columns.str.replace('""', '"', regex=False).str.strip()
# http_success_data_1.rename(columns={
#     'Time': 'timestamp',
#     'count(kube_pod_info{pod=~"chain-1.*"}) by (app)': 'chain-1',
#     'count(kube_pod_info{pod=~"chain-2.*"}) by (app)': 'chain-2',
#     'count(kube_pod_info{pod=~"chain-3.*"}) by (app)': 'chain-3'
# }, inplace=True)

# # Normalize the timestamps in the HTTP success data
# http_success_data_1['timestamp'] = http_success_data_1['timestamp'].astype(float) / 1000
# http_success_data_1['timestamp'] = http_success_data_1['timestamp'] - http_success_data_1['timestamp'].iloc[0]

# # Crop the data at the timestamp 950
# http_success_data_1 = http_success_data_1[http_success_data_1['timestamp'] <= 950]

# # Plot the data of the column 'chain-1' from http_success_data_1
# plt.figure(figsize=(10, 5))
# # Add vertical lines for the time until replicas are up
# colors = ['red', 'blue', 'green']
# for time, label, color in zip(time_until_replicas_up, labels, colors):
#     plt.axvline(x=time, color=color, linestyle='--', alpha=0.7, label=f'{label} Replicas Up')
# plt.plot(http_success_data_1['timestamp'], http_success_data_1['chain-1'], label='HTTP Requests')
# plt.xlabel('Time')
# plt.ylabel('Success Rate (requests per second)')
# plt.title('HTTP Request Success Rate for Chain-1')
# plt.legend()
# plt.grid(True)

plt.show()