from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

store: dict = {}

# GET that returns list of keys with 200 code
@app.get("/data")
def list_keys():
    return {"keys": list(store.keys())}


# GET that returns value for a key with 200 code, or 404 if not found
@app.get("/data/{key}")
def get_key(key: str):
    if key not in store:
        raise HTTPException(status_code=404, detail="Key not found")
    
    return {"value": store[key]}


# PUT that creates or updates a key with 201 code if created, or 200 if updated, 400 if the request body is invalid
@app.put("/data/{key}")
async def create_or_update_key(key: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid/missing JSON body")

    if "value" not in body:
        raise HTTPException(status_code=400, detail="No 'value' field in request body")
    
    if key not in store:
        store[key] = body["value"]
        return JSONResponse(status_code=201, content={"message": "Key created"})
    else:
        store[key] = body["value"]
        return JSONResponse(status_code=200, content={"message": "Key updated"})

# DELETE that deletes a key with 200 code if deleted, or 404 if not found
@app.delete("/data/{key}")
def delete_key(key: str):
    if key not in store:
        return JSONResponse(status_code=404, content={"message": "Key not found"})
    
    del store[key]
    return {"message": "Key deleted"}
