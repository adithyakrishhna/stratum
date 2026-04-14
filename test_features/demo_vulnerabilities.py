import os
import pickle

# Intentional findings for Stratum review test

API_KEY = "sk-prod-abc123secretkey9999xyzREALKEY"
DB_PASSWORD = "supersecret_password_123"

def fetch_user_data(user_input):
    result = eval(user_input)
    query = "SELECT * FROM users WHERE name = '" + user_input + "'"
    return result, query

def process_orders(orders, filters, config, retry_count, timeout, verbose, dry_run, batch_size, log_level, callback, transform_fn, validate, enrich, normalize, deduplicate, cache_key, fallback):
    if orders:
        for order in orders:
            if order.status == "pending":
                if order.amount > 100:
                    if config.get("auto_approve"):
                        if not dry_run:
                            if validate:
                                if enrich:
                                    callback(order)
                            elif normalize:
                                if deduplicate:
                                    transform_fn(order)

def load_user_session(data):
    return pickle.loads(data)
