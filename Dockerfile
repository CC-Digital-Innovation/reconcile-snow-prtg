FROM python:3.8-slim
LABEL maintainer="Jonny Le <jonny.le@computacenter.com>"

# install curl and jq
RUN apt-get update && apt-get install -y curl jq

# install sops
RUN curl -OL https://github.com/mozilla/sops/releases/download/v3.7.1/sops_3.7.1_amd64.deb \
    && apt-get -y install ./sops_3.7.1_amd64.deb \
    && rm sops_3.7.1_amd64.deb

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY src .

EXPOSE 80

# Switch for development
# CMD [ "gunicorn", "main:app", "--bind", "0.0.0.0:80", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker" ]
CMD [ "./build-script.sh" ]
