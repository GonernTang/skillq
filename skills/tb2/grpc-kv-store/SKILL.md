---
name: grpc-kv-store
description: Build a key-value store service exposed over gRPC — define the protobuf contract, implement a concurrency-safe store, wire up the server/client, and add streaming, TTL, and persistence. Use when creating a gRPC KV/cache service, designing Get/Put/Delete/Watch RPCs, or turning an in-memory map into a networked, thread-safe store.
---

# gRPC Key-Value Store

## Overview

A KV store over gRPC is four decoupled layers. Build and verify them in order — never
skip ahead, because each layer's bugs are invisible until the one below it works.

1. **Contract** — a `.proto` file defining messages and the `KVStore` service.
2. **Store** — a concurrency-safe in-memory map (the actual data structure).
3. **Server** — a thin adapter that maps RPC requests onto store calls + error codes.
4. **Client** — a typed stub, plus a CLI or tests to exercise it.

Keep the store logic (layer 2) free of any gRPC types. The server (layer 3) is the ONLY
place `context`, status codes, and protobuf messages meet the store. This separation lets
you unit-test the store without a network and swap transports later.

## When to use

- Building a networked cache, config store, session store, or feature-flag service.
- You need typed, cross-language clients (gRPC generates stubs for Go/Python/Java/etc.).
- You want streaming updates (`Watch`) or bidirectional sync — gRPC's strength over REST.

If you only need HTTP/JSON for browsers, plain REST is simpler. gRPC shines for
service-to-service and streaming.

## The contract (proto)

Design the service surface first — it's the hardest thing to change later. A minimal,
complete KV contract:

```proto
syntax = "proto3";
package kvstore.v1;
option go_package = "example.com/kv/gen/kvstore/v1;kvstorev1";

service KVStore {
  rpc Get(GetRequest) returns (GetResponse);
  rpc Put(PutRequest) returns (PutResponse);
  rpc Delete(DeleteRequest) returns (DeleteResponse);
  rpc List(ListRequest) returns (ListResponse);        // prefix scan
  rpc Watch(WatchRequest) returns (stream WatchEvent); // server-streaming
}

message GetRequest  { string key = 1; }
message GetResponse { bytes value = 1; bool found = 2; int64 version = 3; }

message PutRequest    { string key = 1; bytes value = 2; int64 ttl_seconds = 3; }
message PutResponse   { int64 version = 1; }

message DeleteRequest  { string key = 1; }
message DeleteResponse { bool existed = 1; }

message ListRequest  { string prefix = 1; }
message ListResponse { repeated string keys = 1; }

message WatchRequest { string key_prefix = 1; }
message WatchEvent {
  enum Type { UNSPECIFIED = 0; PUT = 1; DELETE = 2; }
  Type type = 1; string key = 2; bytes value = 3; int64 version = 4;
}
```

Design rules that repeatedly bite people:
- **`bytes value`, not `string`.** Values are arbitrary blobs; `string` forces UTF-8.
- **Return `found`/`existed` bools** instead of relying on empty values — an empty value
  is a valid stored value and must be distinguishable from a miss.
- **Version/revision counter** on every mutation enables optimistic concurrency and lets
  `Watch` clients detect gaps. Cheap to add now, painful to retrofit.
- **`option go_package`** (and the equivalent for your language) must be set or codegen
  emits garbage import paths.
- **Version the package** (`kvstore.v1`) from day one so breaking changes get a `v2`.

Generate stubs with `protoc` / `buf`. Prefer `buf generate` — it handles plugins and
lint/breaking-change checks. Never hand-edit generated files.

## The store (concurrency-safe map)

This is where correctness lives. A plain `map` is not safe for concurrent use — gRPC
handlers run on many goroutines simultaneously, so every access needs synchronization.

```go
type entry struct {
    value   []byte
    version int64
    expires time.Time // zero = no TTL
}

type Store struct {
    mu     sync.RWMutex
    data   map[string]entry
    clock  int64                 // monotonic version counter
}

func New() *Store { return &Store{data: make(map[string]entry)} }

func (s *Store) Get(key string) ([]byte, int64, bool) {
    s.mu.RLock()
    e, ok := s.data[key]
    s.mu.RUnlock()
    if !ok || e.expired(time.Now()) {
        return nil, 0, false
    }
    return e.value, e.version, true
}

func (s *Store) Put(key string, value []byte, ttl time.Duration) int64 {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.clock++
    e := entry{value: value, version: s.clock}
    if ttl > 0 {
        e.expires = time.Now().Add(ttl)
    }
    s.data[key] = e
    return s.clock
}

func (e entry) expired(now time.Time) bool {
    return !e.expires.IsZero() && now.After(e.expires)
}
```

Non-negotiables:
- **`RWMutex`, not `Mutex`.** Reads dominate in a KV store; `RLock` lets them run in
  parallel. But guard EVERY field access — a lone unguarded read is a data race that
  `go test -race` will catch and production won't until it corrupts memory.
- **Copy slices at the boundary** if callers may mutate them. Storing a caller's `[]byte`
  and later reading it back aliases the same memory. Copy on `Put` if in doubt.
- **Lazy TTL expiry** (check `expired` on read) is simplest. Add a background sweeper only
  when memory from dead keys becomes a problem — a `time.Ticker` goroutine that scans and
  deletes. Don't build the sweeper until you need it.
- **Monotonic version counter** under the write lock — never a wall clock (clocks go
  backward; `Date.now()`/`time.Now()` for versioning breaks ordering guarantees).

## The server (RPC → store adapter)

The handler's whole job: unpack the request, call the store, map the result to a response
or a gRPC status code. No business logic here.

```go
func (s *server) Get(ctx context.Context, r *pb.GetRequest) (*pb.GetResponse, error) {
    if r.Key == "" {
        return nil, status.Error(codes.InvalidArgument, "key must not be empty")
    }
    v, ver, ok := s.store.Get(r.Key)
    return &pb.GetResponse{Value: v, Found: ok, Version: ver}, nil
}

func (s *server) Delete(ctx context.Context, r *pb.DeleteRequest) (*pb.DeleteResponse, error) {
    if r.Key == "" {
        return nil, status.Error(codes.InvalidArgument, "key must not be empty")
    }
    return &pb.DeleteResponse{Existed: s.store.Delete(r.Key)}, nil
}
```

gRPC status-code discipline (clients branch on these — get them right):
- `InvalidArgument` — malformed/empty key, oversized value. Validate at the top of every handler.
- `NotFound` — only if your API contract treats a missing key as an error. For `Get`,
  prefer returning `found=false` with `OK`; reserve `NotFound` for operations that require
  the key to exist.
- `DeadlineExceeded` / `Canceled` — honor `ctx`. In long loops (List, Watch) check
  `ctx.Err()` and bail; never ignore context cancellation.
- `ResourceExhausted` — value/key over a size limit. Set `MaxRecvMsgSize` and reject early.
- `Internal` — unexpected failures only. Don't leak internal error strings to clients.

Server bootstrap:

```go
lis, _ := net.Listen("tcp", ":50051")
gs := grpc.NewServer(grpc.MaxRecvMsgSize(4 << 20))
pb.RegisterKVStoreServer(gs, &server{store: kv.New()})
reflection.Register(gs) // enables grpcurl; drop in locked-down prod
gs.Serve(lis)
```

Always register **reflection** in dev — it lets `grpcurl` introspect the service without
the `.proto`, which is the fastest way to smoke-test.

## Streaming Watch

Server-streaming is the pattern most people get wrong. The handler holds the stream open
and pushes events until the client disconnects or context is canceled.

```go
func (s *server) Watch(r *pb.WatchRequest, stream pb.KVStore_WatchServer) error {
    ch, cancel := s.store.Subscribe(r.KeyPrefix) // buffered chan of events
    defer cancel()
    for {
        select {
        case <-stream.Context().Done():
            return stream.Context().Err() // client went away — clean exit
        case ev := <-ch:
            if err := stream.Send(ev); err != nil {
                return err
            }
        }
    }
}
```

Rules:
- **Always select on `stream.Context().Done()`** or you leak a goroutine per dead client.
- **Buffer subscriber channels** and decide a slow-consumer policy: drop events, or
  disconnect the laggard. An unbuffered channel lets one slow watcher stall every writer.
- **`cancel()` on return** unsubscribes — otherwise the store keeps sending into a dead
  channel forever.

## The client

```go
conn, _ := grpc.NewClient("localhost:50051", grpc.WithTransportCredentials(insecure.NewCredentials()))
defer conn.Close()
c := pb.NewKVStoreClient(conn)

ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
defer cancel()
c.Put(ctx, &pb.PutRequest{Key: "a", Value: []byte("1")})
resp, _ := c.Get(ctx, &pb.GetRequest{Key: "a"})
```

- **Reuse one `conn`** across the whole app — it multiplexes over HTTP/2. Never dial per
  request; connection setup is expensive and defeats gRPC's point.
- **Always set a per-call timeout** via `context.WithTimeout`. A missing deadline means a
  hung server hangs the client forever.
- `insecure` credentials are for local dev ONLY. Use TLS (`credentials.NewTLS`) anywhere real.

## Persistence (optional layer)

In-memory is fine until a restart wipes everything. Add durability without touching the
store's public API:
- **Append-only log**: write each mutation to a WAL before applying; replay on startup.
  Simplest crash-safe option.
- **Snapshot + WAL**: periodically serialize the whole map, truncate the log. Bounds
  replay time.
- **Embedded engine** (BoltDB, Badger, Pebble): swap the `map` for the engine behind the
  same `Store` interface. Reach for this once you outgrow memory.

Guard the WAL with the same write lock as the map so the log order matches apply order.

## Verification checklist

Test bottom-up; a green layer below makes the next layer's failures obvious.

1. **`go test -race ./...`** — the store MUST pass with the race detector. Concurrency bugs
   that pass without `-race` will corrupt data in production. This is the single most
   important check.
2. **Store unit tests** with no network: Get-miss, Put-then-Get, Delete, TTL expiry,
   overwrite bumps version, concurrent Put/Get under `-race` with many goroutines.
3. **Smoke-test with grpcurl** once the server runs:
   ```
   grpcurl -plaintext -d '{"key":"a","value":"aGk="}' localhost:50051 kvstore.v1.KVStore/Put
   grpcurl -plaintext -d '{"key":"a"}' localhost:50051 kvstore.v1.KVStore/Get
   ```
   (value is base64 because the field is `bytes`.)
4. **Client integration test**: start the server on a random port, dial, exercise every
   RPC including a `Watch` that receives an event after a concurrent `Put`.
5. **Error paths**: empty key → `InvalidArgument`; canceled context mid-`Watch` → clean
   exit, no leaked goroutine (check with `runtime.NumGoroutine` before/after).

## Common pitfalls

- **Unguarded map access** — the #1 bug. Every read and write goes through the lock. Run `-race`.
- **`string` value fields** truncating binary data at the first invalid UTF-8 byte.
- **Empty value indistinguishable from miss** — return an explicit `found` bool.
- **No context deadline on the client** → hung calls. No context check in server loops →
  ignored cancellation and goroutine leaks.
- **Dialing per request** instead of reusing the connection.
- **Editing generated `.pb.go` files** — regenerate from the `.proto` instead.
- **Wall-clock versions** — use a monotonic counter under the write lock.
- **Unbuffered Watch channels** letting one slow client stall all writers.