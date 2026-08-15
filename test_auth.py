import os
from pathlib import Path

import boto3
from dotenv import load_dotenv


env_path = Path(__file__).resolve().parent / ".env"

load_dotenv(
    dotenv_path=env_path,
    override=True,
)

access_key = os.getenv("AWS_ACCESS_KEY_ID")
secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
region = os.getenv("AWS_REGION")

print("ENV:", env_path)
print("exists:", env_path.exists())

print(
    "access:",
    repr(access_key[:4] + "..." + access_key[-4:])
    if access_key
    else "<missing>",
)

print(
    "access length:",
    len(access_key) if access_key else None,
)

print(
    "secret length:",
    len(secret_key) if secret_key else None,
)

print(
    "region:",
    region,
)

session = boto3.Session(
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name=region,
)

credentials = session.get_credentials()

print()
print("resolved access:", credentials.access_key[:4] + "..." + credentials.access_key[-4:])
print("resolved token:", "<set>" if credentials.token else "<not set>")

print()
print("Calling STS...")

sts = session.client("sts")
print(sts.get_caller_identity())
