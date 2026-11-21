FROM spark@sha256:edc304196cbd7619933658d6e01b082b12bcef45ba96223d4a56584c0b4b1fcf
WORKDIR /

# Reset to root to run installation tasks
USER 0


COPY jars.lock.json fetch-jars.py /tmp/alias-spark-build/
# Hadoop common is already supplied by the base's matching shaded client runtime.
RUN python3 /tmp/alias-spark-build/fetch-jars.py /tmp/alias-spark-build/jars.lock.json /opt/spark/jars

WORKDIR /opt/spark/work-dir
ENTRYPOINT [ "/opt/entrypoint.sh" ]

# Specify the User that the actual main process will run as
ARG spark_uid=185
USER ${spark_uid}
