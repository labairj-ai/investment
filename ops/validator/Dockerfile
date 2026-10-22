# Operator-only provisioning. Never build this image during candidate validation.
ARG APPROVED_BASE_IMAGE
FROM ${APPROVED_BASE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /opt/validator/requirements.lock
RUN python -m pip install --no-cache-dir -r /opt/validator/requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 65534:65534
WORKDIR /tmp
