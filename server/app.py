from fastapi import FastAPI

from server import database

try:
    connection = database.get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT version();")
    print("Database connected")
except Exception as e:
    print("Dataabase error: ", str(e))


async def lifespan(router: FastAPI):
    router.state.model = object()
    print("ML model loaded")
    yield
    print("ML model unloaded")


app = FastAPI(lifespan=lifespan)


@app.get("/ping")
async def ping():
    return {"message": "pong!"}