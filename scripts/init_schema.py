"""Create missing tables; never drop existing data."""
import argparse
import os
from pathlib import Path
import re
import ydb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("schema")
    args = parser.parse_args()
    source = "\n".join(
        line for line in Path(args.schema).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    credentials = ydb.AccessTokenCredentials(os.environ["YC_IAM_TOKEN"])
    with ydb.Driver(endpoint=os.environ["YDB_ENDPOINT"],
                    database=os.environ["YDB_DATABASE"],
                    credentials=credentials) as driver:
        driver.wait(timeout=10, fail_fast=True)
        session = driver.table_client.session().create()
        try:
            for statement in source.split(";"):
                statement = statement.strip()
                if not statement:
                    continue
                match = re.match(r"CREATE TABLE (\w+)", statement, re.I)
                if not match:
                    raise ValueError("Only CREATE TABLE statements are allowed")
                table = match.group(1)
                try:
                    session.describe_table(os.environ["YDB_DATABASE"] + "/" + table)
                except ydb.SchemeError:
                    session.execute_scheme(statement)
                    print("Created", table)
                else:
                    print("Preserved existing table", table)
        finally:
            session.delete()


if __name__ == "__main__":
    main()
