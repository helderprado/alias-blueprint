FROM jupyterhub/k8s-hub:3.2.1

USER root
RUN pip3 install --no-cache-dir -U \
    PyJWT \
    kubernetes

USER ${NB_USER}

