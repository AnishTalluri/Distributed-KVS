#!/bin/bash
# tests/test_pt1.sh — Integration tests for Part 1 (single-node KVS)
# Run this in a second WSL terminal while the container is running.
# Assumes: KVS running on localhost:8081 with an empty store.

BASE_URL="http://localhost:8081"
PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# check_status <expected_code> <description> <curl_args...>
check_status() {
    local expected=$1
    local desc=$2
    shift 2

    local actual
    actual=$(curl -s -o /dev/null -w "%{http_code}" "$@")

    if [ "$actual" = "$expected" ]; then
        echo -e "${GREEN}PASS${NC}  [$actual]  $desc"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}FAIL${NC}  [expected $expected, got $actual]  $desc"
        FAIL=$((FAIL + 1))
    fi
}

# check_body <expected_body> <description> <curl_args...>
check_body() {
    local expected=$1
    local desc=$2
    shift 2

    local actual
    actual=$(curl -s "$@")

    if [ "$actual" = "$expected" ]; then
        echo -e "${GREEN}PASS${NC}  [body]  $desc"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}FAIL${NC}  [expected $expected, got $actual]  $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo -e "${BLUE}Running Part 1 tests against $BASE_URL${NC}\n"

# 1. GET on empty store -> 200
check_status 200 "GET /data (empty store)" \
    "$BASE_URL/data"

# 2. PUT new key -> 201
check_status 201 "PUT /data/foo (new key)" \
    -X PUT "$BASE_URL/data/foo" \
    -H "Content-Type: application/json" \
    -d '{"value": "bar"}'

# 2b. GET /data returns key-value pairs, not a key list
check_body '{"foo":"bar"}' "GET /data body shape" \
    "$BASE_URL/data"

# 3. GET the key back -> 200
check_status 200 "GET /data/foo (existing key)" \
    "$BASE_URL/data/foo"

# 4. PUT same key again -> 200 (update, not create)
check_status 200 "PUT /data/foo (update existing)" \
    -X PUT "$BASE_URL/data/foo" \
    -H "Content-Type: application/json" \
    -d '{"value": "baz"}'

# 5. GET missing key -> 404
check_status 404 "GET /data/nope (missing key)" \
    "$BASE_URL/data/nope"

# 6. PUT with no 'value' field -> 400
check_status 400 "PUT /data/foo (missing value field)" \
    -X PUT "$BASE_URL/data/foo" \
    -H "Content-Type: application/json" \
    -d '{}'

# 6b. Body is valid JSON but not an object -> 400
check_status 400 "PUT /data/foo (body is a number)" \
    -X PUT "$BASE_URL/data/foo" \
    -H "Content-Type: application/json" \
    -d '5'

# 6c. Value is not a string -> 400
check_status 400 "PUT /data/foo (value is not a string)" \
    -X PUT "$BASE_URL/data/foo" \
    -H "Content-Type: application/json" \
    -d '{"value": 5}'

# 7. DELETE existing key -> 200
check_status 200 "DELETE /data/foo" \
    -X DELETE "$BASE_URL/data/foo"

# 8. DELETE the same key again -> 404
check_status 404 "DELETE /data/foo (already deleted)" \
    -X DELETE "$BASE_URL/data/foo"

echo ""
echo -e "${BLUE}Results:${NC} ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"

# Exit non-zero if any test failed (useful for CI later)
[ "$FAIL" -eq 0 ]