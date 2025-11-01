# Common environment variables for all Lambdas
COMMON_ENV_VARS=(
    'BUCKET_NAME=${ROOT_BUCKET}'
    'TABLE_NAME=${TABLE_NAME}'
    'LOCALSTACK_ENDPOINT=http://localstack:4566'
    'AWS_REGION=${REGION}'
)

# Lambda-specific configurations
declare -A LAMBDAS
declare -A LAMBDA_ENV_VARS

# Format: name:path:http_method
LAMBDAS["upload_images"]="uploadImages:POST"
# use '|' to separate multiple KEY=VALUE entries; keep empty string if none
LAMBDA_ENV_VARS["upload_images"]='PRESIGN_EXP=900|UPLOAD_LIMIT=10485760'

LAMBDAS["list_images"]="listImages:GET"
LAMBDA_ENV_VARS["list_images"]='PAGE_SIZE=10'

LAMBDAS["delete_images"]="deleteImages:DELETE"
LAMBDA_ENV_VARS["delete_images"]=''

# event-driven lambda (no API route)
LAMBDAS["s3_listener"]=""
LAMBDA_ENV_VARS["s3_listener"]=''