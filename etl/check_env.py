import glob
import pandas as pd
from pyspark.sql import SparkSession

print("--- CSV files found ---")
for f in glob.glob("data/source/*.csv"):
    df = pd.read_csv(f)
    print(f"\n{f}  ->  {df.shape[0]} rows, {df.shape[1]} columns")
    print(list(df.columns))
    print(df.head(3).to_string())

print("\n--- Spark check ---")
spark = SparkSession.builder.master("local[*]").appName("check").getOrCreate()
print("Spark version:", spark.version)
print("Spark range count:", spark.range(5).count())
spark.stop()