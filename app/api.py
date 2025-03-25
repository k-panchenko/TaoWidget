import time
from fastapi import FastAPI, Request
from app.routers import router


app = FastAPI(title="TaoWidget API")

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

app.include_router(router)
