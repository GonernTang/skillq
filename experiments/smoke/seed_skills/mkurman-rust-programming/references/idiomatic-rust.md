# Idiomatic Rust Reference

## API Shape

- Follow the Rust API Guidelines for naming, trait implementations, error types, and documentation expectations.
- Prefer `From` for infallible conversions and `TryFrom` for fallible conversions.
- Accept `impl AsRef<Path>` or `&Path` for filesystem APIs when callers should not have to allocate a `PathBuf`.
- Return owned data only when the callee creates it, stores it, or must detach it from an input lifetime.
- Use builders only when construction has many optional fields or validation needs to be staged.

### Examples

```rust
impl TryFrom<&str> for WorkspaceId {
    type Error = WorkspaceIdError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        if value.is_empty() {
            return Err(WorkspaceIdError::Empty);
        }
        Ok(Self(value.to_owned()))
    }
}
```

```rust
pub fn write_snapshot(path: &std::path::Path, snapshot: &Snapshot) -> Result<(), SnapshotError> {
    let json = serde_json::to_vec_pretty(snapshot)?;
    std::fs::write(path, json).map_err(|source| SnapshotError::Write {
        path: path.to_path_buf(),
        source,
    })
}
```

## Error Handling

- Use one domain error enum per boundary when callers need to match variants.
- Use context-rich error wrapping at application edges where matching is less important than diagnosis.
- Avoid losing source errors when crossing layers.
- Do not convert all failures to strings early; that removes type information and makes tests weaker.
- Treat `expect("...")` messages as explanations of why the invariant should hold, not restatements of the failed operation.

### Examples

```rust
let agent = agents
    .get(agent_id)
    .ok_or(AgentError::UnknownAgent { id: agent_id.clone() })?;
```

```rust
let port = std::env::var("PORT")
    .expect("PORT must be set by the launcher before daemon startup")
    .parse::<u16>()?;
```

## Ownership And Borrowing

- Prefer `&str` over `&String`, `&[T]` over `&Vec<T>`, and `&Path` over `&PathBuf` in parameters.
- Clone where it simplifies ownership at a real boundary, such as spawning tasks, storing data, or decoupling from a lock guard.
- Avoid returning references tied to lock guards unless the API makes that lifetime obvious and useful.
- Keep mutation local. If multiple call sites need coordinated mutation, extract a method that owns the invariant.

### Examples

```rust
fn summarize(messages: &[Message]) -> Summary {
    messages.iter().fold(Summary::default(), Summary::include)
}
```

```rust
let previous = self.pending.take();
if let Some(job) = previous {
    self.archive(job)?;
}
```

## Async And Concurrency

- Never hold a `MutexGuard` or `RwLock` guard across `.await` unless the lock type and invariant were chosen for that exact behavior.
- Start independent futures before awaiting them when ordering is not required.
- Propagate cancellation by letting futures drop cleanly; avoid detached tasks unless the task has a lifecycle owner.
- Use channels to serialize ownership-heavy workflows instead of sharing mutable state through broad locks.
- Bound queues when producers can outrun consumers.

### Examples

```rust
let (profile, permissions) = tokio::try_join!(
    profile_store.load(user_id),
    permission_store.load(user_id),
)?;
```

```rust
let (tx, mut rx) = tokio::sync::mpsc::channel::<WorkItem>(128);
tokio::spawn(async move {
    while let Some(item) = rx.recv().await {
        worker.process(item).await;
    }
});
```

## Performance

- Measure before trading clarity for micro-optimizations.
- Use `Cow`, arenas, or interning only after allocation pressure is known.
- Prefer iterator adapters for straightforward transformations and loops for early exits, mutation, or clearer error handling.
- Avoid collecting intermediate `Vec`s unless the collection is reused, sorted, indexed, or needed for ownership.

### Examples

```rust
let names: std::collections::HashSet<&str> = users.iter().map(|user| user.name.as_str()).collect();

if names.contains(candidate_name) {
    return Err(UserError::DuplicateName);
}
```

## Tests

- Put unit tests near logic with narrow contracts.
- Add integration tests at crate boundaries, CLI behavior, IPC contracts, persistence, or policy decisions.
- Use property tests for parsers, routing, normalization, and other logic with many equivalent inputs.
- Include regression tests for borrow-checker, lifetime, or concurrency fixes when the failure mode can be represented deterministically.

### Examples

```rust
#[test]
fn parses_workspace_id_from_non_empty_string() {
    let id = WorkspaceId::try_from("main").unwrap();

    assert_eq!(id.as_str(), "main");
}
```

## Useful Commands

```bash
cargo fmt --all --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo doc --workspace --no-deps
```
