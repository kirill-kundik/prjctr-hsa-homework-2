import os
import random
import time

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from faker import Faker
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from statsd import StatsClient

stats = StatsClient('telegraf', 8125, prefix='performance')

es = AsyncElasticsearch(f'http://{os.environ["ELASTIC_HOST"]}:{os.environ["ELASTIC_PORT"]}')
mongo = AsyncIOMotorClient(
    f'mongodb://{os.environ["MONGO_USER"]}:{os.environ["MONGO_PASS"]}@{os.environ["MONGO_HOST"]}:{os.environ["MONGO_PORT"]}/'
)
mongo_db = mongo["fastapi"]

app = FastAPI()

fake = Faker()


@app.on_event("startup")
async def startup():
    if not (await es.indices.exists(index="fastapi")):
        await es.indices.create(index="fastapi")


@app.on_event("shutdown")
async def shutdown():
    await es.close()


def gen_row():
    return {"name": fake.name(), "address": fake.address(), "text": fake.text()}


def gen_data(max_n=None):
    return [gen_row() for _ in range(random.randint(1, max_n or 10))]


async def ingest_elastic():
    await async_bulk(es, [{"_index": "fastapi", "doc": doc} for doc in gen_data()])


async def search_elastic():
    return await es.search(
        index="fastapi", body={"query": {"multi_match": {"query": fake.name()}}}
    )


async def insert_mongo():
    await mongo_db.test_collection.insert_many(gen_data())


async def query_mongo():
    cursor = mongo_db.test_collection.find({"name": {"$regex": fake.name()}})
    await cursor.to_list(length=100)


@app.get("/")
async def index():
    start = time.time()
    actions = ["create", "search"]
    types = ["elastic", "mongo"]
    action = random.choice(actions)
    type_ = random.choice(types)

    with stats.pipeline() as pipe:
        if type_ == "elastic":
            if action == "create":
                await ingest_elastic()
            else:
                await search_elastic()
        else:
            if action == "create":
                await insert_mongo()
            else:
                await query_mongo()

        pipe.incr(f'request.successful.count,type={type_},action={action}', 1)
        pipe.timing(f'request.successful.time,type={type_},action={action}', time.time() - start)

    return {"status": "ok"}
