FROM tiangolo/uvicorn-gunicorn:python3.8
LABEL maintainer="Jonny Le <jonny.le@computacenter.com>"
COPY ./requirements.txt /app/requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app