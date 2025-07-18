#!/bin/bash
set -e

export KUBECONFIG=/etc/kubernetes/admin.conf

# === CONFIGURATION ===
GRAFANA_PASSWORD="admin"
NAMESPACE="monitoring"
# =====================

# 1. Add Helm Repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# 2. Create Monitoring Namespace
kubectl create namespace "$NAMESPACE" || true

# 3. Install Metrics Server (with TLS disabled for compatibility)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Patch metrics server deployment to disable TLS verification
kubectl -n kube-system patch deployment metrics-server \
  --type=json \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args", "value": [
    "--cert-dir=/tmp",
    "--secure-port=4443",
    "--kubelet-insecure-tls",
    "--kubelet-preferred-address-types=InternalIP,Hostname,InternalDNS,ExternalDNS,ExternalIP"
  ]}'
  
# 4. Install Prometheus
helm install prometheus prometheus-community/prometheus \
  --namespace monitoring \
  --set server.service.type=NodePort

# 5. Install Grafana
helm install grafana grafana/grafana \
  --namespace "$NAMESPACE" \
  --set adminPassword="$GRAFANA_PASSWORD" \
  --set service.type=NodePort

# 6. Output access instructions
GRAFANA_PORT=$(kubectl get svc grafana -n "$NAMESPACE" -o jsonpath='{.spec.ports[0].nodePort}')
NODE_IP=$(hostname -I | awk '{print $1}')

cat <<EOF

Monitoring stack deployed!
-----------------------------------------
Grafana is accessible at: http://$NODE_IP:$GRAFANA_PORT
Login with:
  Username: admin
  Password: $GRAFANA_PASSWORD

Prometheus is also available inside the cluster at:
  http://prometheus.$NAMESPACE.svc.cluster.local

Metrics Server is installed with TLS verification disabled.
Use 'kubectl top nodes' and 'kubectl top pods' to check metrics.
Use 'kubectl get pods -n $NAMESPACE' to monitor component status.
EOF