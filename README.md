# DeathstarBench Deployment

This repository provides scripts to deploy the **Social Network** application from the [DeathStarBench](https://github.com/delimitrou/DeathStarBench) benchmark suite on a **Kubernetes cluster**, along with optional **monitoring** tools and our **Context-Aware HPA** (Horizontal Pod Autoscaler) configuration.

## Repository Structure

```
.
├── install_k8s.sh                    # Installs Kubernetes with containerd and Flannel
├── README.md                         # This file
├── deathstar-bench/                  # DeathStarBench deployment files
│   ├── deploy/                       # Deployment scripts
│   │   ├── deploy_socialnetowrk.sh   # Deploys the Social Network app using Helm
│   │   ├── fetch_ports.sh            # Gets the exposed ports of services
│   │   └── reset_testbed.sh          # Resets all SocialNetwork pods
│   ├── hpa/                          # HPA configuration files
│   │   ├── hpa_values.yaml           # Values for HPA configuration
│   │   └── service_values.yaml       # Values for service deployment
│   └── monitoring/                   # Monitoring stack files
│       ├── deploy_monitoring.sh      # Deploys Prometheus & Grafana
│       └── grafana-dashboard.json    # Grafana dashboard configuration
├── k6/                               # Load testing files
│   ├── k6_csv_report_parser.py       # CSV report parser for k6 results
│   ├── k6_loader.js                  # k6 load testing script
│   └── reports/                      # Directory for test reports
└── prom/                             # Prometheus configuration
    └── prometheus-adapter-values.yaml # Prometheus adapter values
```

## Quickstart

### 1. Install Kubernetes

#### Option 1: Bare-metal Kubernetes on Ubuntu 24.04

```bash
chmod +x install_k8s.sh
./install_k8s.sh
```

This will:
- Install `kubeadm`, `kubelet`, and `kubectl`
- Configure `containerd` as the container runtime
- Apply the Flannel CNI
- Initialize a single-node cluster

#### Option 2: Kind 

Requirements: Docker

```bash
brew install kind 
kind create cluster --name socialnetwork
kubectl cluster-info --context ocialnetwork
```

### 2. (Optional) Deploy Monitoring Stack

```bash
cd deathstar-bench/monitoring
chmod +x deploy_monitoring.sh
./deploy_monitoring.sh
```

Installs:
- Prometheus
- Grafana

### 3. Deploy the Social Network App

Requirements:
```bash
sudo apt install libssl-dev (previous requirement)
sudo apt install zlib1g-dev
sudo apt-get install luarocks
sudo luarocks install luasocket
```

Once ready:

```bash
cd deathstar-bench/deploy
chmod +x deploy_socialnetowrk.sh
./deploy_socialnetowrk.sh
```

This script:
- Clones DeathStarBench (with PR #352)
- Initializes submodules
- Installs the app via Helm 
- Compiles wrk loader

### 4. Fetch Service Ports

```bash
cd deathstar-bench/deploy
chmod +x fetch_ports.sh
./fetch_ports.sh
```

Lists exposed NodePorts for UI and services.

### 5. Reset all SocialNetwork pods

```bash
cd deathstar-bench/deploy
chmod +x reset_testbed.sh
./reset_testbed.sh
```

Deletes and redeploys all SocialNetwork pods, except monitoring.

### 6. Context-Aware HPA

TODO: Modify the prometheus adapter values in order to export the desired metrics to triggrer autoscaling.
Once done, see how to add custom HPA values and metrics.


## Custom values for HPA and main services

You can customize HPA values via `hpa_values.yaml`.
You can customize service resources via `service_values.yaml`.

In order to add an external metric in HPA follow this example:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: <your-service-name>-hpa
  namespace: <your-namespace>
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <your-deployment-name>
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: <your-custom-metric-name-defined-in-prom-adapter>
        target:
          type: Value
          value: <your-target-value>
```

To apply the changes:
```bash
cd deathstar-bench/hpa
kubectl apply -f hpa_values.yaml -n socialnetwork
kubectl apply -f service_values.yaml -n socialnetwork
```


## Load Testing:

You can use the `k6` tool with the custom loader :

```bash
cd k6
xk6 build latest
```

To run the benchmark, make sure the proper nginx IP address is configured.

```bash
./k6 run k6_loader.js --out csv=reports/report-name.csv   
```

