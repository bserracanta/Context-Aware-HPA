#!/bin/bash

# Define monitoring-related namespaces or pod name patterns to exclude
EXCLUDED_NAMESPACES=("monitoring" "kube-system")
EXCLUDED_PODS=("prometheus" "jaeger" "grafana" "kube-state-metrics")

# Get all pods in the default namespace (or specify the correct one if different)
ALL_PODS=$(kubectl get pods --no-headers -o custom-columns=":metadata.name")

for POD in $ALL_PODS; do
    # Check if the pod is in the excluded list
    SHOULD_DELETE=true
    
    # Skip if the pod name matches any excluded patterns
    for EXCLUDED in "${EXCLUDED_PODS[@]}"; do
        if [[ "$POD" == *"$EXCLUDED"* ]]; then
            SHOULD_DELETE=false
            break
        fi
    done
    
    # Delete the pod if it is not excluded
    if [ "$SHOULD_DELETE" = true ]; then
        echo "Deleting pod: $POD"
        kubectl delete pod "$POD"
    fi
done

# Wait for the pods to be fully terminated
echo "Waiting for pods to terminate..."
#kubectl wait --for=delete pod --all --timeout=60s
sleep 60

# Wait for all non-monitoring pods to be redeployed and ready
echo "Waiting for all application pods to be redeployed and ready..."
while true; do
    NOT_READY_PODS=$(kubectl get pods --no-headers | grep -vE "$(IFS='|'; echo "${EXCLUDED_PODS[*]}")" | grep -v "Running" | grep -v "Completed" | wc -l)
    
    if [ "$NOT_READY_PODS" -eq 0 ]; then
        echo "All application pods are ready."
        break
    fi
    
    echo "Waiting for pods to be ready... ($NOT_READY_PODS pods still not ready)"
    sleep 5

done


# # Run the test script with a specified query rate
# QUERY_RATE=$1
# if [ -z "$QUERY_RATE" ]; then
#     echo "Error: Please provide a query rate as an argument."
#     exit 1
# fi

# echo "Running test with query rate: $QUERY_RATE"
# LOG_FILE="test_log_$(date +'%Y%m%d_%H%M%S').log"
# nohup python3 loader_no_ramp.py --query_rate "$QUERY_RATE" > "$LOG_FILE" 2>&1 &
# TEST_PID=$!

# echo "Test is running in the background. Logs are being saved in $LOG_FILE"

# # Wait for up to 15 minutes (900 seconds) for the test to complete
# TIMER=0
# while kill -0 $TEST_PID 2>/dev/null; do
#     sleep 10
#     TIMER=$((TIMER + 10))
#     if [ "$TIMER" -ge 900 ]; then
#         echo "Test taking too long, stopping it manually..."
#         kill -SIGINT $TEST_PID
#         wait $TEST_PID || true  # Ensure wait doesn't block if process is already terminated
#         break
#     fi
# done

# echo "Test finished or terminated. Proceeding with file processing..."

# # Find the generated test result file
# test_file=$(ls test_*.txt | tail -n 1)
# if [ -z "$test_file" ]; then
#     echo "Error: No test output file found."
#     exit 1
# fi

# # Create a folder with the test date and query rate
# TEST_DATE=$(date +"%Y%m%d")
# OUTPUT_FOLDER="${TEST_DATE}_QR${QUERY_RATE}"
# mkdir -p "$OUTPUT_FOLDER"

# # Move the test file into the newly created folder
# echo "Moving $test_file to $OUTPUT_FOLDER/"
# mv "$test_file" "$OUTPUT_FOLDER/"

# echo "Test completed. Results saved in $OUTPUT_FOLDER/"