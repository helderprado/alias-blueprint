ARG base_img=spark@sha256:edc304196cbd7619933658d6e01b082b12bcef45ba96223d4a56584c0b4b1fcf

FROM $base_img
WORKDIR /

# Reset to root to run installation tasks
USER 0


RUN wget -O /opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar
RUN wget -O /opt/spark/jars/postgresql-42.1.1.jar https://repo1.maven.org/maven2/org/postgresql/postgresql/42.1.1/postgresql-42.1.1.jar
RUN wget -O /opt/spark/jars/hadoop-common-3.3.4.jar https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-common/3.3.4/hadoop-common-3.3.4.jar
RUN wget -O /opt/spark/jars/hadoop-aws-3.3.4.jar https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar

WORKDIR /opt/spark/work-dir
ENTRYPOINT [ "/opt/entrypoint.sh" ]

# Specify the User that the actual main process will run as
ARG spark_uid=185
USER ${spark_uid}
