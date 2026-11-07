from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI() # Initialize FastAPI application

store: dict = {} # In-memory key-value store

# This EMPTY object is being declared so that NULL is an actual value
# (i.e. if a DELETE request is made and the key holds NULL,
# it should be able to delete the value and return 200, only 404 if the key is missing)
_MISSING = object()

# GET that returns list of keys with 200 code
@app.get("/data")
def list_keys():
    return {"keys": list(store.keys())}


# GET that returns value for a key with 200 code,
# 404 if not found
@app.get("/data/{key}")
def get_key(key: str):
    if key not in store:
        raise HTTPException(status_code=404, detail="Key not found")
    
    return {"value": store[key]}


# PUT that creates or updates a key with...
# 201 code if created,
# 200 if updated,
# 400 if the request body is invalid
@app.put("/data/{key}")
async def create_or_update_key(key: str, request: Request):
    """
    Create or update a key-value pair in the store.
    """
    try:
        # "await" allows the server to handle other requests concurrently by freeing up the thread while waiting for the request body to be read
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid/missing JSON body")

    # Check that the request body is a dictionary
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    # Check that the request body contains a 'value' field
    if "value" not in body:
        raise HTTPException(status_code=400, detail="No 'value' field in request body")

    # Check if the key already exists in the store
    if key not in store:
        store[key] = body["value"]
        return JSONResponse(status_code=201, content={"message": "Key created"})
    else:
        store[key] = body["value"]
        return JSONResponse(status_code=200, content={"message": "Key updated"})

# DELETE that deletes a key with 200 code if deleted,
# 404 if not found
@app.delete("/data/{key}")
def delete_key(key: str):
    removed = store.pop(key, _MISSING)
    if removed is _MISSING:
        raise HTTPException(status_code=404, detail="Key not found")
    
    return {"message": "Key deleted"}
