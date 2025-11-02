FROM python:3.11-slim

# ensure tzdata and tools for jq if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates build-essential curl git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copy only dependency info if you have one, otherwise install required packages
# If you maintain src/common/requirements.txt we'll install it
COPY src/common/requirements.txt /tmp/requirements.txt
RUN if [ -s /tmp/requirements.txt ]; then pip install -r /tmp/requirements.txt; fi

# Install test tools
RUN pip install --no-cache-dir pytest pytest-mock boto3 botocore

# Copy project
COPY . /app

# Set PYTHONPATH so tests import from src package
ENV PYTHONPATH=/app/src

# Run tests by default
CMD ["pytest", "-q", "tests/unit"]