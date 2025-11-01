#!/usr/bin/env bash
set -euo pipefail

# Load Lambda + API configuration
source ./scripts/deploy_config.sh

LOCALSTACK_CONTAINER="localstack-image-svc"
LOCALSTACK_SERVICE="localstack"
REGION=${AWS_REGION:-us-east-1}
TABLE_NAME="ImagesMetadata"
LAMBDA_NAME="upload_images"
API_NAME="image-service-api"
ROOT_BUCKET="image-service-root"


# Helper to create API Gateway resource and method
create_api_resource() {
    local name=$1
    local path=$2
    local method=$3
    local api_id=$4
    local parent_id=$5

    echo "Ensuring API resource for ${name}: ${method} /${path}"

    # Try to find existing resource with the exact path (returns id or "None"/empty)
    resource_id=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-resources \
        --rest-api-id "${api_id}" \
        --query "items[?path==\`/${path}\`].id | [0]" --output text)

    if [ -z "${resource_id}" ] || [ "${resource_id}" = "None" ]; then
        echo "Resource /${path} not found, creating..."
        resource_id=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway create-resource \
            --rest-api-id "${api_id}" \
            --parent-id "${parent_id}" \
            --path-part "${path}" \
            --query 'id' --output text)
        echo "Created resource id: ${resource_id}"
    else
        echo "Found existing resource id: ${resource_id} for path /${path}"
    fi

    # Create method only if missing
    if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-method \
        --rest-api-id "${api_id}" --resource-id "${resource_id}" --http-method "${method}" >/dev/null 2>&1; then
        echo "Method ${method} already exists on /${path}"
    else
        echo "Creating method ${method} on /${path}"
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway put-method \
            --rest-api-id "${api_id}" \
            --resource-id "${resource_id}" \
            --http-method "${method}" \
            --authorization-type "NONE"
    fi

    # Create integration only if missing
    if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-integration \
        --rest-api-id "${api_id}" --resource-id "${resource_id}" --http-method "${method}" >/dev/null 2>&1; then
        echo "Integration for ${method} on /${path} already exists"
    else
        echo "Creating integration for ${method} -> Lambda ${name}"
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway put-integration \
            --rest-api-id "${api_id}" \
            --resource-id "${resource_id}" \
            --http-method "${method}" \
            --type "AWS_PROXY" \
            --integration-http-method "POST" \
            --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/arn:aws:lambda:${REGION}:000000000000:function:${name}/invocations"
    fi

    # Add permission for API Gateway to invoke Lambda if not already present
    # (awslocal add-permission will fail if statement-id exists; check first)
    stmt_id="apigw-invoke-${api_id}-${resource_id}-${method}"
    if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda get-policy --function-name "${name}" >/dev/null 2>&1; then
        if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda get-policy --function-name "${name}" \
            --query "Policy" --output text 2>/dev/null | grep -q "${stmt_id}"; then
            echo "Lambda permission ${stmt_id} already present"
        else
            echo "Adding lambda permission ${stmt_id}"
            docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda add-permission \
                --function-name "${name}" \
                --statement-id "${stmt_id}" \
                --action "lambda:InvokeFunction" \
                --principal apigateway.amazonaws.com \
                --source-arn "arn:aws:execute-api:${REGION}:000000000000:${api_id}/*/${method}/${path}" || true
        fi
    else
        echo "No policy for lambda ${name} yet; attempting to add permission"
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda add-permission \
            --function-name "${name}" \
            --statement-id "${stmt_id}" \
            --action "lambda:InvokeFunction" \
            --principal apigateway.amazonaws.com \
            --source-arn "arn:aws:execute-api:${REGION}:000000000000:${api_id}/*/${method}/${path}" || true
    fi
}

deploy_lambda() {
    local name=$1
    local TMP_ZIP="/tmp/${name}.zip"
    
    echo "Deploying Lambda: ${name}"
    
    # Package Lambda
    rm -f "${TMP_ZIP}"
    cd src
    zip -r "${TMP_ZIP}" "lambdas/${name}" common -x "*.pyc" "__pycache__/*" >/dev/null
    cd ..
    
    # Copy to LocalStack
    docker cp "${TMP_ZIP}" "${LOCALSTACK_CONTAINER}:/tmp/${name}.zip"
    
    # Build environment variables and store in a file to avoid escaping issues
    local env_vars
    env_vars=$(build_env_vars "$name")
    echo "$env_vars" > /tmp/lambda_env.json
    
    if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda get-function \
        --function-name "${name}" >/dev/null 2>&1; then
        echo "Updating existing Lambda function: ${name}"
        
        # Update code
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda update-function-code \
            --function-name "${name}" \
            --zip-file "fileb:///tmp/${name}.zip"
            
        # Update configuration using the environment file
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda update-function-configuration \
            --function-name "${name}" \
            --timeout 15 \
            --environment "$(cat /tmp/lambda_env.json)" \
            --handler "lambdas.${name}.handler.handler"
    else
        echo "Creating new Lambda function: ${name}"
        # Create new function using the environment file
        docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda create-function \
            --function-name "${name}" \
            --runtime python3.9 \
            --role "arn:aws:iam::000000000000:role/lambda-role" \
            --handler "lambdas.${name}.handler.handler" \
            --zip-file "fileb:///tmp/${name}.zip" \
            --timeout 15 \
            --environment "$(cat /tmp/lambda_env.json)" \
            --region ${REGION}
    fi
    
    rm -f /tmp/lambda_env.json
    echo "Lambda deployment completed: ${name}"
}

# Helper to build environment variables JSON
build_env_vars() {
    local lambda_name=$1
    # Start with the required "Variables" wrapper
    local vars='{"Variables":{'

    # Add common vars
    for var in "${COMMON_ENV_VARS[@]}"; do
        IFS='=' read -r key value <<< "$var"
        local expanded_value
        expanded_value=$(eval "echo \"$value\"")
        vars+='"'$key'":"'$expanded_value'",'
    done

    # Add lambda-specific vars
    local spec="${LAMBDA_ENV_VARS[$lambda_name]:-}"
    if [ -n "${spec}" ]; then
        IFS='|' read -r -a kvs <<< "$spec"
        for var in "${kvs[@]}"; do
            [ -z "$var" ] && continue
            IFS='=' read -r key value <<< "$var"
            local expanded_value
            expanded_value=$(eval "echo \"$value\"")
            vars+='"'$key'":"'$expanded_value'",'
        done
    fi

    # Remove trailing comma and close both objects
    vars="${vars%,}"
    vars+='}}'
    
    # Validate and format JSON using jq
    echo "$vars" | jq -c .
}

get_or_create_api() {
    local name="$1"
    echo "=== API Gateway Debug ==="
    echo "Looking up API by name: '${name}'"

    # List all APIs first for debugging
    echo "Current APIs:"
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-rest-apis

    # Get API ID with extra careful cleanup of output
    API_ID=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-rest-apis \
        --query "items[?name=='${name}'].id | [0]" \
        --output text | sed 's/[[:space:]]//g')

    echo "Raw API_ID lookup result: '${API_ID}'"

    if [ -z "${API_ID}" ] || [ "${API_ID}" = "None" ] || [ "${API_ID}" = "null" ]; then
        echo "Creating new API '${name}'..."
        API_ID=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway create-rest-api \
            --name "${name}" \
            --query 'id' \
            --output text | sed 's/[[:space:]]//g')
        echo "Created new API with ID: '${API_ID}'"
    else
        echo "Found existing API with ID: '${API_ID}'"
    fi

    # Validate API exists and is accessible
    echo "Validating API ID '${API_ID}'..."
    if ! docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-resources \
        --rest-api-id "${API_ID}" > /dev/null 2>&1; then
        echo "ERROR: Could not access API with ID '${API_ID}'" >&2
        return 1
    fi

    echo "API validation successful"
    echo "======================="
    echo "${API_ID}"
}

deploy_api_stage() {
    local api_id=$1
    local stage_name=${2:-local}
    echo "Creating deployment for API ${api_id} stage ${stage_name}..."
    # create-deployment always creates a new deployment; safe to call to publish recent changes
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway create-deployment \
      --rest-api-id "${api_id}" --stage-name "${stage_name}"
    echo "Deployment completed."
}

wait_for_api() {
    local api_id="$1"
    local retries=5
    echo "Waiting for API Gateway ${api_id} to be ready..."
    
    for i in $(seq 1 $retries); do
        if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-resources \
            --rest-api-id "${api_id}" >/dev/null 2>&1; then
            echo "API Gateway is ready"
            return 0
        fi
        echo "Attempt ${i}/${retries}: API not ready yet, waiting..."
        sleep 2
    done
    return 1
}

# SQS / S3 notification / event-source mapping helpers
create_or_get_queue() {
    local qname=$1
    echo "Ensuring SQS queue exists: ${qname}"
    QUEUE_URL=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal sqs get-queue-url --queue-name "${qname}" --query 'QueueUrl' --output text 2>/dev/null | tr -d '\r\n' || true)
    if [ -n "${QUEUE_URL}" ] && [ "${QUEUE_URL}" != "None" ]; then
        echo "Found queue URL: ${QUEUE_URL}"
    else
        echo "Creating queue: ${qname}"
        QUEUE_URL=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal sqs create-queue --queue-name "${qname}" --query 'QueueUrl' --output text | tr -d '\r\n')
        echo "Created queue URL: ${QUEUE_URL}"
    fi

    QUEUE_ARN=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal sqs get-queue-attributes --queue-url "${QUEUE_URL}" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text | tr -d '\r\n')
    echo "Queue ARN: ${QUEUE_ARN}"
}

set_sqs_policy_for_s3() {
    local queue_arn=$1
    local bucket_arn=$2
    echo "Ensuring SQS policy allows S3 -> ${queue_arn} from ${bucket_arn}"

    EXISTING_POLICY=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal sqs get-queue-attributes \
        --queue-url "${QUEUE_URL}" --attribute-names Policy --query 'Attributes.Policy' --output text 2>/dev/null || true)
    if echo "${EXISTING_POLICY}" | grep -q "${bucket_arn}" >/dev/null 2>&1; then
        echo "SQS policy already allows this bucket"
        return 0
    fi

    # Build policy JSON on host
    local policy
    policy=$(cat <<EOF
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Sid":"AllowS3SendMessage",
      "Effect":"Allow",
      "Principal":"*",
      "Action":"SQS:SendMessage",
      "Resource":"${queue_arn}",
      "Condition":{"ArnEquals":{"aws:SourceArn":"${bucket_arn}"}}
    }
  ]
}
EOF
)

    # Compact policy JSON
    compact_policy=$(echo "${policy}" | jq -c .)

    # Escape the compact_policy into a JSON string value using jq -Rs
    escaped_policy=$(printf '%s' "${compact_policy}" | jq -Rs .)

    # Write attributes JSON to secure host temp file (Policy is a string value)
    tmpf=$(mktemp)
    printf '%s' "{\"Policy\": ${escaped_policy}}" > "${tmpf}"

    # Copy into container and apply
    docker cp "${tmpf}" "${LOCALSTACK_CONTAINER}:/tmp/queue_attrs.json"
    rm -f "${tmpf}"

    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal sqs set-queue-attributes \
        --queue-url "${QUEUE_URL}" \
        --attributes file:///tmp/queue_attrs.json

    docker compose exec -T ${LOCALSTACK_SERVICE} rm -f /tmp/queue_attrs.json >/dev/null 2>&1 || true

    echo "SQS policy set"
}

configure_bucket_notification_to_sqs() {
    local bucket=$1
    local queue_arn=$2
    echo "Ensuring S3 bucket notification for ${bucket} -> ${queue_arn}"

    EXISTING=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal s3api get-bucket-notification-configuration --bucket "${bucket}" 2>/dev/null || true)
    if echo "${EXISTING}" | grep -q "${queue_arn}" >/dev/null 2>&1; then
        echo "Bucket notification already configured for ${queue_arn}"
        return 0
    fi

    # Build notification config and apply (overwrites existing configuration)
    docker compose exec -T ${LOCALSTACK_SERVICE} sh -c "cat > /tmp/s3_notification.json <<'EOF'
{ \"QueueConfigurations\": [ { \"QueueArn\": \"${queue_arn}\", \"Events\": [ \"s3:ObjectCreated:*\" ] } ] }
EOF
"
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal s3api put-bucket-notification-configuration --bucket "${bucket}" --notification-configuration file:///tmp/s3_notification.json
    docker compose exec -T ${LOCALSTACK_SERVICE} rm -f /tmp/s3_notification.json >/dev/null 2>&1 || true
    echo "Bucket notification configured"
}

create_event_source_mapping_for_queue() {
    local lambda_name=$1
    local queue_arn=$2
    echo "Ensuring event source mapping for lambda=${lambda_name} -> ${queue_arn}"

    EXISTING_UUID=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda list-event-source-mappings --function-name "${lambda_name}" --event-source-arn "${queue_arn}" --query 'EventSourceMappings[0].UUID' --output text 2>/dev/null | tr -d '\r\n' || true)
    if [ -n "${EXISTING_UUID}" ] && [ "${EXISTING_UUID}" != "None" ]; then
        echo "Event source mapping already exists (UUID=${EXISTING_UUID})"
        return 0
    fi

    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda create-event-source-mapping \
        --function-name "${lambda_name}" \
        --event-source-arn "${queue_arn}" \
        --batch-size 10 \
        --starting-position LATEST >/dev/null
    echo "Created event source mapping for ${lambda_name}"
}


echo "Ensuring root S3 bucket exists: ${ROOT_BUCKET}"
if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal s3api head-bucket --bucket "${ROOT_BUCKET}" >/dev/null 2>&1; then
    echo "S3 bucket ${ROOT_BUCKET} already exists"
else
    echo "Creating S3 bucket ${ROOT_BUCKET}..."
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal s3api create-bucket --bucket "${ROOT_BUCKET}"
fi

echo "Ensuring DynamoDB table exists: ${TABLE_NAME}"
if docker compose exec -T ${LOCALSTACK_SERVICE} awslocal dynamodb describe-table --table-name "${TABLE_NAME}" >/dev/null 2>&1; then
    echo "DynamoDB table ${TABLE_NAME} already exists"
else
    echo "Creating DynamoDB table ${TABLE_NAME}..."
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal dynamodb create-table \
      --table-name "${TABLE_NAME}" \
      --attribute-definitions AttributeName=user_id,AttributeType=S AttributeName=image_id,AttributeType=S \
      --key-schema AttributeName=user_id,KeyType=HASH AttributeName=image_id,KeyType=RANGE \
      --billing-mode PAY_PER_REQUEST

    echo "Waiting for DynamoDB table ${TABLE_NAME} to become ACTIVE..."
    docker compose exec -T ${LOCALSTACK_SERVICE} awslocal dynamodb wait table-exists --table-name "${TABLE_NAME}"
fi



# Create API Gateway
echo "Creating API Gateway: ${API_NAME}"
echo "Creating or updating API Gateway..."
# First, list existing APIs
EXISTING_APIS=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway get-rest-apis)
echo "Existing APIs: ${EXISTING_APIS}"

# Try to find existing API by name
API_ID=$(echo "${EXISTING_APIS}" | jq -r --arg NAME "${API_NAME}" '.items[] | select(.name==$NAME) | .id')
echo "Found API_ID: ${API_ID}"

if [ -z "${API_ID}" ]; then
    echo "Creating new API Gateway: ${API_NAME}"
    API_RESULT=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway create-rest-api \
        --name "${API_NAME}" \
        --description "LocalStack Image Service API" \
        --endpoint-configuration "{ \"types\": [\"EDGE\"] }")
    echo "API Creation Result: ${API_RESULT}"
    API_ID=$(echo "${API_RESULT}" | jq -r .id)
    echo "New API_ID: ${API_ID}"
fi

# Wait for API to be ready
if ! wait_for_api "${API_ID}"; then
    echo "ERROR: API Gateway failed to initialize" >&2
    exit 1
fi

echo "Getting root resource for API ${API_ID}..."
ROOT_RESOURCE_ID=$(docker compose exec -T ${LOCALSTACK_SERVICE} awslocal apigateway \
    get-resources --rest-api-id "${API_ID}" \
    --query 'items[?path==`/`].id' --output text)
echo "Root resource ID: ${ROOT_RESOURCE_ID}"

if [ -z "${ROOT_RESOURCE_ID}" ]; then
    echo "ERROR: Failed to get root resource ID" >&2
    exit 1
fi

# Deploy each Lambda and create API routes (skip event-driven lambdas with empty path)
for lambda in "${!LAMBDAS[@]}"; do
    IFS=: read -r path method <<< "${LAMBDAS[$lambda]}"
    deploy_lambda "${lambda}"

    if [ -n "${path}" ]; then
        create_api_resource "${lambda}" "${path}" "${method}" "${API_ID}" "${ROOT_RESOURCE_ID}"
    else
        echo "Skipping API resource creation for event-driven lambda: ${lambda}"
    fi
done

# --- S3 -> SQS -> Lambda wiring (idempotent) ---
QUEUE_NAME="image-events-queue"
# create/get queue and ARN
create_or_get_queue "${QUEUE_NAME}"

# allow S3 to send to the queue (idempotent)
BUCKET_ARN="arn:aws:s3:::${ROOT_BUCKET}"
set_sqs_policy_for_s3 "${QUEUE_ARN}" "${BUCKET_ARN}"

# configure bucket notifications (idempotent check inside function)
configure_bucket_notification_to_sqs "${ROOT_BUCKET}" "${QUEUE_ARN}"

# map the queue to the lambda that processes S3 notifications (s3_listener)
# ensure the lambda name matches deploy_config (LAMBDAS key). Here it's "s3_listener"
create_event_source_mapping_for_queue "s3_listener" "${QUEUE_ARN}"
# --- end wiring ---

# Deploy API
echo "Deploying API..."
deploy_api_stage "${API_ID}" "local"

echo "Deployment complete!"
echo "API endpoint: http://localhost:4566/restapis/${API_ID}/local/_user_request_/"