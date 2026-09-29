# Builder stage.
FROM python:3.14.7-alpine3.24 AS builder

WORKDIR /app

# Set environment variables to reduce writing to disk and improve performance.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Upgrade pip and install requirements.
COPY requirements.txt .
RUN python -m pip install pip==26.2.1 && \
    python -m pip install --no-cache-dir -r requirements.txt


# Runtime stage.
FROM python:3.14.7-alpine3.24 AS runtime

LABEL org.opencontainers.image.authors="Anthony Farina"

WORKDIR /app

# Patch alpine packages.
RUN apk update && apk upgrade --no-cache

# Set environment variables to reduce writing to disk and improve performance.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy app's dependencies.
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages

# Remove pip from the runtime image to reduce size and vulnerabilities.
RUN rm -rf /usr/local/lib/python3.14/site-packages/pip

# Let Python know where the app's dependencies are located.
ENV PYTHONPATH="/usr/local/lib/python3.14/site-packages"

# Copy source code and make the local user own the /app directory and all the files within it.
# This allows the user to write files to the system.
RUN chown -R appuser:appgroup /app
COPY --chown=appuser:appgroup ./src .

# Set non-root user and group to run the app via their UID and GID.
USER 10014:10015

# Expose ports for the app.
EXPOSE 80

# Set the entry for the container to run the app.
ENTRYPOINT ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]