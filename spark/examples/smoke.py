"""Distributed computation and optional S3 round trip using synthetic data only."""
import argparse
import uuid
from pyspark.sql import SparkSession

parser = argparse.ArgumentParser()
parser.add_argument('--s3-prefix')
args = parser.parse_args()
spark = SparkSession.builder.appName('ALIAS Spark smoke check').getOrCreate()
try:
    data = spark.range(1000, numPartitions=2)
    assert data.count() == 1000
    if args.s3_prefix:
        path = args.s3_prefix.rstrip('/') + '/' + str(uuid.uuid4())
        data.write.mode('errorifexists').parquet(path)
        assert spark.read.parquet(path).count() == 1000
        # Remove only this run's randomly named synthetic dataset after verification.
        target = spark._jvm.org.apache.hadoop.fs.Path(path)
        assert target.getFileSystem(spark._jsc.hadoopConfiguration()).delete(target, True)
    print('ALIAS Spark distributed smoke check passed.')
finally:
    spark.stop()
