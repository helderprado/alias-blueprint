FROM jupyterhub/k8s-hub@sha256:1f8db66b29c597d4a26ec9eef08df4472e896a64f50739d5f242a9c18dd43e3c

USER root
COPY requirements.txt /tmp/hub-requirements.txt
RUN pip3 install --no-cache-dir --no-deps --require-hashes --only-binary=:all: -r /tmp/hub-requirements.txt

USER ${NB_USER}

