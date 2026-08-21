#!/usr/bin/env python3
"""Seeds the bookly-orders DynamoDB table from external_service/data/orders.json
-- the same fixture the local external_service uses, so local dev and the
real AWS deployment start from identical order data. Safe to re-run any
time to reset the table back to a pristine state (put_item overwrites).
"""
import json
from decimal import Decimal
from pathlib import Path

import boto3

REGION = "eu-west-2"
TABLE_NAME = "bookly-orders"
FIXTURE = Path(__file__).resolve().parent.parent / "external_service" / "data" / "orders.json"


def main():
    with open(FIXTURE) as f:
        orders = json.load(f, parse_float=Decimal)

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    for order in orders:
        table.put_item(Item=order)
        print(f"seeded {order['order_id']}")


if __name__ == "__main__":
    main()
