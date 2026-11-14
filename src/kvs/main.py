from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import os
import asyncio

app = FastAPI() # Initialize FastAPI application

store: dict = {} # In-memory key-value store

view: list = [] # View represents nodes and their IDs

my_id: int = int(os.environ.get("NODE_IDENTIFIER", "0")) # Node identifier that runs locally with uvicorn

write_lock = asyncio.Lock()

# Unique marker so pop can tell a missing key apart from any stored value
_MISSING = object()

# Get the primary node from the view
def get_primary():
    if not view:
        return None
    return min(view, key=lambda node: node["id"])

# Check if the current node is the primary node
def is_primary():
    primary = get_primary()
    if primary is not None and primary["id"] == my_id:
        return True
    return False

# Helper function for request methods to make sure the view is in place (not empty) before running any /data handlers
def require_view():
    # If the view is empty
    if not view:
        raise HTTPException(status_code=503, detail="View required before any requests can be made")

# GET that returns a ping message with 200 code
@app.get("/ping")
async def ping():
    return {"message": "We're good to go!"}

# PUT that allows for harness to give the nodes currently up IDs via a view
@app.put("/view")
async def set_view(request: Request):
    # Read the HTTP request body, return 400 if there is no valid view
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid/missing JSON body")

    # Check request body is a dict, else return 400
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    # Check if view is even in the body
    if "view" not in body:
        raise HTTPException(status_code=400, detail="View not in request body")

    # Check if view is a 'list' type
    if not isinstance(body["view"], list):
        raise HTTPException(status_code=400, detail="View must be a list type")

    # Clear the old list of nodes so the view can be updated with the new list of nodes
    view.clear()
    view.extend(body["view"])

    # Return a success message that view has been set (200 OK defaults on this return)
    return {"message": "View successfully set"}

# GET that returns key-value pairs with 200 code
@app.get("/data")
def list_keys():
    # Check for view
    require_view()

    return dict(store)

# GET that returns value for a key with 200 code,
# 404 if not found
@app.get("/data/{key}")
def get_key(key: str):
    # Check for view
    require_view()

    if key not in store:
        raise HTTPException(status_code=404, detail="Key not found")
    
    return {"value": store[key]}

# PUT that creates or updates a key with...
# 201 code if created,
# 200 if updated,
# 400 if the request body is invalid
@app.put("/data/{key}")
async def create_or_update_key(key: str, request: Request):
    # Check for view
    require_view()

    # Create or update a key-value pair in the store.
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

    # Check that the 'value' is a string
    if not isinstance(body["value"], str):
        raise HTTPException(status_code=400, detail="'value' must be a string")

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
    # Check for view
    require_view()

    removed = store.pop(key, _MISSING)
    if removed is _MISSING:
        raise HTTPException(status_code=404, detail="Key not found")
    
    return {"message": "Key deleted"}