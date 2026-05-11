# Databricks notebook source
# ML — Customer Segmentation (RFM + K-Means)
# ============================================
# Input:  retail_prod.bronze.customer_360 (RFM features from DLT pipeline)
# Model:  K-Means clustering, K=4
# Output: Cluster labels written to retail_prod.bronze.customer_segments
#         (standalone Delta table — DLT-managed tables are read-only externally)
#         Model registered in MLflow Model Registry
#
# Segments (business labels, not "Cluster 0"):
#   Champions      — high recency, high frequency, high monetary
#   Loyal          — moderate-high on all three
#   At Risk        — previously good, now declining recency
#   Lost Customers — low on all three, long since purchased
#
# Run weekly alongside demand forecasting.

import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = SparkSession.builder.getOrCreate()
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment("/Shared/retail-lakehouse/segmentation")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CATALOG   = "retail_prod"
N_CLUSTERS = 4
MODEL_NAME = f"{CATALOG}.ml.customer_segmentation"

SEGMENT_LABELS = {
    # Assigned after fitting based on centroid analysis (recency DESC, freq ASC)
    # These are set dynamically in label_clusters() below
}

# ---------------------------------------------------------------------------
# Load features
# ---------------------------------------------------------------------------

def load_rfm_features() -> pd.DataFrame:
    df = spark.table(f"{CATALOG}.bronze.customer_360")
    features_df = (
        df.select(
            "customer_id",
            "rfm_recency_score",
            "rfm_frequency_score",
            "rfm_monetary_score",
        )
        .filter(
            F.col("rfm_recency_score").isNotNull() &
            F.col("rfm_frequency_score").isNotNull() &
            F.col("rfm_monetary_score").isNotNull()
        )
        .toPandas()
    )
    print(f"Loaded {len(features_df):,} customers with complete RFM features.")
    return features_df


def label_clusters(kmeans: KMeans, feature_cols: list) -> dict:
    """
    Assign business segment names based on centroid positions.
    Champions = highest monetary + frequency + recency.
    Lost = lowest across all three.
    """
    centroids = pd.DataFrame(kmeans.cluster_centers_, columns=feature_cols)
    centroids["composite_score"] = (
        centroids["rfm_recency_score"] +
        centroids["rfm_frequency_score"] +
        centroids["rfm_monetary_score"]
    )
    centroids_sorted = centroids.sort_values("composite_score", ascending=False)
    labels = ["Champions", "Loyal Customers", "At Risk", "Lost Customers"]
    return {int(centroids_sorted.index[i]): labels[i] for i in range(N_CLUSTERS)}


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train_and_log(features_df: pd.DataFrame):
    feature_cols = ["rfm_recency_score", "rfm_frequency_score", "rfm_monetary_score"]
    X = features_df[feature_cols].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    with mlflow.start_run(run_name="kmeans_rfm_segmentation") as run:
        mlflow.log_param("n_clusters", N_CLUSTERS)
        mlflow.log_param("dataset_version", "retail_prod.bronze.customer_360")
        mlflow.log_param("n_customers", len(features_df))

        kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(X_scaled)

        sil_score = silhouette_score(X_scaled, cluster_labels)
        mlflow.log_metric("silhouette_score", sil_score)
        print(f"Silhouette score: {sil_score:.4f} (target > 0.3)")

        segment_map = label_clusters(kmeans, feature_cols)
        mlflow.log_dict(segment_map, "segment_label_map.json")

        # Log model — wrap scaler + kmeans in a Pipeline so sklearn can
        # serialize them as a single estimator, then infer the UC-required signature.
        from sklearn.pipeline import Pipeline as SKPipeline
        from mlflow.models import infer_signature

        seg_pipeline = SKPipeline([("scaler", scaler), ("kmeans", kmeans)])
        sample_input  = features_df[feature_cols].iloc[:5]
        sample_output = pd.Series(
            seg_pipeline.predict(sample_input.values), name="cluster_label"
        )
        signature = infer_signature(sample_input, sample_output)

        mlflow.sklearn.log_model(
            sk_model=seg_pipeline,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            signature=signature,
            input_example=sample_input.iloc[:2],
        )

        run_id = run.info.run_id
        print(f"MLflow run_id: {run_id}")

    return cluster_labels, segment_map, run_id, sil_score


# ---------------------------------------------------------------------------
# Write segments to standalone Delta table (customer_segments)
# ---------------------------------------------------------------------------
# NOTE: DLT-managed streaming tables (like customer_360) are read-only from
# external notebooks — Delta MERGE is not permitted on them.
# We write segment labels to a separate standalone table instead.
# ---------------------------------------------------------------------------

def writeback_segments(features_df: pd.DataFrame, cluster_labels: np.ndarray,
                       segment_map: dict, run_id: str):
    features_df = features_df.copy()
    features_df["cluster_id"]        = cluster_labels
    features_df["customer_segment"]  = features_df["cluster_id"].map(segment_map)
    features_df["run_id"]            = run_id
    features_df["segmented_at"]      = pd.Timestamp.now()

    segments_df = spark.createDataFrame(
        features_df[["customer_id", "cluster_id", "customer_segment", "run_id", "segmented_at"]]
    )

    # Overwrite the entire customer_segments table each run (full refresh).
    # This is a standalone Delta table — not DLT-managed — so writes are fine.
    (
        segments_df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(f"{CATALOG}.bronze.customer_segments")
    )

    print(f"Wrote {len(features_df):,} segment labels to {CATALOG}.bronze.customer_segments")

    # Log segment distribution
    dist = features_df["customer_segment"].value_counts().to_dict()
    print("Segment distribution:", dist)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    features_df = load_rfm_features()
    cluster_labels, segment_map, run_id, sil_score = train_and_log(features_df)

    if sil_score < 0.30:
        print(f"WARNING: Silhouette score {sil_score:.4f} is below 0.30 threshold.")
        print("Model registered in Staging. Will NOT be auto-promoted to Production.")
    else:
        print(f"Silhouette score {sil_score:.4f} passes threshold. Model in Staging.")
        print("model_validation.py will promote to Production after checks pass.")

    writeback_segments(features_df, cluster_labels, segment_map, run_id)
    print("Segmentation complete.")
