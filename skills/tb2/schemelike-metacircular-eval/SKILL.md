---
name: schemelike-metacircular-eval
description: Build a gRPC Python key-value store server — define .proto, generate stubs, implement servicer, and run with grpcio. Use for creating a lightweight KV store over gRPC.
---

# gRPC Python KV Store Server

## Overview

This skill explains how to create a minimal gRPC key-value store server in Python. The server exposes two RPCs: `GetVal(key)` returns the stored value (int32, default 0 if missing), and `SetVal(key, val)` stores/overwrites a value and returns it. The implementation uses an in-memory dictionary.

## Steps

1. **Install dependencies**  
   Ensure `grpcio` and `grpcio-tools` are installed with compatible versions (e.g., `grpcio==1.73.0`, `grpcio-tools==1.73.0`).

2. **Write the `.proto` file**  
   Define the service and messages:
   ```protobuf
   syntax = "proto3";
   service KVStore {
       rpc GetVal(GetValRequest) returns (GetValResponse);
       rpc SetVal(SetValRequest) returns (SetValResponse);
   }
   message GetValRequest { string key = 1; }
   message GetValResponse { int32 val = 1; }
   message SetValRequest { string key = 1; int32 val = 2; }
   message SetValResponse { int32 val = 1; }
   ```

3. **Generate Python stubs**  
   ```bash
   python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. kv-store.proto
   ```
   This produces `kv_store_pb2.py` and `kv_store_pb2_grpc.py`.

4. **Implement the servicer**  
   Create `server.py` and define a class inheriting from `KVStoreServicer`. Override `GetVal` and `SetVal` using an in-memory dictionary:
   ```python
   import grpc
   import kv_store_pb2
   import kv_store_pb2_grpc

   class Server(kv_store_pb2_grpc.KVStoreServicer):
       def __init__(self):
           self.store = {}
       def GetVal(self, request, context):
           val = self.store.get(request.key, 0)
           return kv_store_pb2.GetValResponse(val=val)
       def SetVal(self, request, context):
           self.store[request.key] = request.val
           return kv_store_pb2.SetValResponse(val=request.val)
   ```

5. **Run the server**  
   In `main`:
   ```python
   def serve():
       server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
       kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
       server.add_insecure_port('[::]:5328')
       server.start()
       server.wait_for_termination()

   if __name__ == '__main__':
       serve()
   ```
   Start the server in the background (e.g., `nohup python server.py &`).

6. **Test with a client**  
   Create a client that imports the stubs and calls RPCs:
   ```python
   import grpc
   import kv_store_pb2
   import kv_store_pb2_grpc

   channel = grpc.insecure_channel('localhost:5328')
   stub = kv_store_pb2_grpc.KVStoreStub(channel)
   print(stub.SetVal(kv_store_pb2.SetValRequest(key='foo', val=42)))
   print(stub.GetVal(kv_store_pb2.GetValRequest(key='foo')))
   ```

## Common pitfalls

- **Port already in use**: Choose an unused port; use `[::]:<port>` for IPv6 compatibility.
- **Protobuf syntax errors**: Use `int32` or `int64` for numeric values; avoid `float` unless needed.
- **Stale stubs**: Regenerate stubs after changing the `.proto` file.
- **Wrong import names**: The generated module names depend on the `.proto` filename; use the correct stem (e.g., `kv_store_pb2` if the file is `kv-store.proto`).

## Testing checklist

- `SetVal("key", 42)` returns `val: 42`
- `GetVal("key")` returns `val: 42`
- `GetVal("nonexistent")` returns `val: 0` (default)
- Overwrite: `SetVal("key", 99)` then `GetVal("key")` returns `val: 99`

## Extension roadmap

Once the basic server works: add authentication (SSL/TLS), persistent storage (e.g., SQLite), streaming RPCs, or a health check endpoint.