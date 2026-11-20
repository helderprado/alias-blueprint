FROM apache/airflow@sha256:b16e19f925ae0dcabaa2271b37212891ed68bf74e26c2db61f46dddd7d502937

COPY requirements.txt /

RUN pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: -r /requirements.txt

