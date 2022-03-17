import os

import pandas as pd

from vicedtools.gcp import (upload_csv_to_bigquery,
                            PAT_MOST_RECENT_SCHEMA,
                            PAT_MOST_RECENT_CLUSTERING_FIELDS)


def pat_most_recent_to_bq(table_id: str, bucket: str, scores_file:str):
    """Imports student details to BQ from Compass student details export.
    
    Args:
        table_id: The BQ table id for the enrolments data
        bucket: A GCS bucket for temporarily storing the csv for import into BQ.
        scores_file: The path to the PAT most recent scores csv.
    """
    temp_file = os.path.join(os.path.dirname(scores_file), "temp.csv")

    column_rename = {"Username":"StudentCode",
                    "Maths Completed":"MathsDate",
                    "Reading Completed":"ReadingDate",
                    "Maths Year level (at time of test)":"MathsYearLevel",
                    "Reading Year level (at time of test)":"ReadingYearLevel",
                    "Maths Test form": "MathsTestForm",
                    "Reading Test form": "ReadingTestForm",
                    "Maths Score category":"MathsScoreCategory",
                    "Reading Score category":"ReadingScoreCategory"}
    df = pd.read_csv(scores_file)
    df.rename(columns=column_rename, inplace=True)
    df.to_csv(temp_file, index=False)
    upload_csv_to_bigquery(scores_file, PAT_MOST_RECENT_SCHEMA,
                           PAT_MOST_RECENT_CLUSTERING_FIELDS, table_id, bucket)
    os.remove(temp_file)

if __name__ == "__main__":
    from config import (root_dir,
                        oars_folder,
                        pat_most_recent_table_id,
                        bucket)

    if not os.path.exists(root_dir):
        raise FileNotFoundError(f"{root_dir} does not exist as root directory.")
    oars_dir = os.path.join(root_dir, oars_folder)
    if not os.path.exists(oars_dir):
        raise FileNotFoundError(f"{oars_dir} does not exist as a directory.")
    scores_file = os.path.join(oars_dir, "pat most recent.csv")

    pat_most_recent_to_bq(pat_most_recent_table_id, bucket, scores_file)