# Implementation Plan: `no_memcache` Build Tag

## Overview

Split the cache-coupled handler logic out of each service's `server.go` into a pair of build-tag-guarded files (`server_cache.go` / `server_nocache.go`), do the same for each `cmd/` entry point (`init_cache.go` / `init_nocache.go`), and add property-based tests that verify no Memcached calls are made under the `no_memcache` build.

## Tasks

- [ ] 1. Refactor `services/profile` — split handler into cache and no-cache files
  - Move `GetProfiles` out of `server.go` into a new `server_cache.go` tagged `//go:build !no_memcache`; keep the `Server` struct, `Run`, `Shutdown`, and helper types in `server.go` (untagged)
  - Create `server_nocache.go` tagged `//go:build no_memcache` with a `GetProfiles` implementation that queries `profile-db.hotels` directly for every requested hotel ID, logs MongoDB errors with `log.Error().Msgf`, and returns a non-nil error to the caller on failure — no `MemcClient` calls, no writes back to Memcached
  - The `MemcClient *memcache.Client` field stays on the struct in `server.go`; it is left `nil` in the no-cache build and never accessed
  - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.4_

- [ ] 2. Refactor `services/rate` — split handler into cache and no-cache files
  - Move `GetRates` out of `server.go` into `server_cache.go` tagged `//go:build !no_memcache`
  - Create `server_nocache.go` tagged `//go:build no_memcache` with a `GetRates` implementation that queries `rate-db.inventory` directly for every requested hotel ID, sorts results by `TotalRate` descending (same `sort.Sort(ratePlans)` call), logs MongoDB errors, and returns a non-nil error on failure — no `MemcClient` calls
  - _Requirements: 1.2, 1.3, 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Refactor `services/reservation` — split handlers into cache and no-cache files
  - Move `CheckAvailability` and `MakeReservation` out of `server.go` into `server_cache.go` tagged `//go:build !no_memcache`
  - Create `server_nocache.go` tagged `//go:build no_memcache` with direct-MongoDB implementations of both methods: query `reservation-db.number` for capacity and `reservation-db.reservation` for counts, insert reservation records on `MakeReservation`, log errors, return non-nil errors on failure — no `MemcClient` calls, no Memcached writes
  - _Requirements: 1.2, 1.3, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 4. Checkpoint — verify service packages compile under both build variants
  - Run `go build ./services/profile/... ./services/rate/... ./services/reservation/...` from `hotelReservation/`
  - Run `go build -tags no_memcache ./services/profile/... ./services/rate/... ./services/reservation/...`
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Refactor `cmd/profile` — split MemcClient init into cache and no-cache files
  - Extract the `tune.NewMemCClient2(...)` call and the `MemcClient` field assignment from `main.go` into a new `init_cache.go` tagged `//go:build !no_memcache`; expose a `buildServer(...)` helper that returns a fully-initialized `*profile.Server` including `MemcClient`
  - Create `init_nocache.go` tagged `//go:build no_memcache` with a `buildServer(...)` helper that constructs `*profile.Server` without `MemcClient` and without reading `ProfileMemcAddress` from config
  - Update `main.go` to call `buildServer(...)` instead of constructing the struct inline
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 6. Refactor `cmd/rate` — split MemcClient init into cache and no-cache files
  - Same pattern as task 5: extract `tune.NewMemCClient2` into `init_cache.go` (`//go:build !no_memcache`) and create `init_nocache.go` (`//go:build no_memcache`) that omits it; update `main.go` to call `buildServer(...)`
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 7. Refactor `cmd/reservation` — split MemcClient init into cache and no-cache files
  - Same pattern as task 5: `init_cache.go` / `init_nocache.go` / updated `main.go`
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 8. Checkpoint — verify full build under both variants
  - Run `go build ./...` from `hotelReservation/` (default build must succeed)
  - Run `go build -tags no_memcache ./...` (no-cache build must succeed)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 6.1, 6.2_

- [ ] 9. Add property-based tests for the `no_memcache` build
  - Add `pgregory.net/rapid` to `go.mod` / `go.sum` if not already present (`go get pgregory.net/rapid`)
  - [ ] 9.1 Create `services/profile/server_nocache_test.go` tagged `//go:build no_memcache`
    - Implement a spy `MemcClient` wrapper that panics (or records calls) on any method invocation
    - Seed an in-process MongoDB instance (or use a mock) with stub `pb.Hotel` documents
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 9.2 Write property test for profile service — Property 1
    - **Property 1: No Memcached calls in profile service**
    - Generator: random non-empty slice of hotel ID strings (up to 20 IDs)
    - Assert: spy records zero calls; returned `Hotels` slice length equals input ID count
    - Run with minimum 100 iterations (`rapid` default)
    - **Validates: Requirements 2.1, 2.3**

  - [ ] 9.3 Create `services/rate/server_nocache_test.go` tagged `//go:build no_memcache`
    - Same spy/mock pattern; seed `rate-db.inventory` with stub rate plan documents
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 9.4 Write property test for rate service — Property 2
    - **Property 2: No Memcached calls in rate service**
    - Generator: random non-empty slice of hotel ID strings
    - Assert: spy records zero calls; returned `RatePlans` are sorted by `TotalRate` descending
    - Run with minimum 100 iterations
    - **Validates: Requirements 3.1, 3.3**

  - [ ] 9.5 Create `services/reservation/server_nocache_test.go` tagged `//go:build no_memcache`
    - Same spy/mock pattern; seed `reservation-db.number` and `reservation-db.reservation` collections
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 9.6 Write property test for reservation service — Property 3
    - **Property 3: No Memcached calls in reservation service**
    - Generator: random hotel ID string, random in/out date pair where in < out (within a 30-day window)
    - Assert: spy records zero calls for both `CheckAvailability` and `MakeReservation`
    - Run with minimum 100 iterations
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [ ] 10. Final checkpoint — run full test suite under both build variants
  - Run `go test ./...` from `hotelReservation/` (default build, cache path tests)
  - Run `go test -tags no_memcache ./...` (no-cache build, property tests included)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 6.1, 6.2, 6.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests (9.2, 9.4, 9.6) are only compiled and run with `-tags no_memcache`
- The `MemcClient` field is intentionally kept on the `Server` struct in all builds to avoid changing the struct definition; it is simply `nil` and never accessed in the no-cache build
- The no-cache error handling uses `log.Error` + return (not `log.Panic`) for MongoDB failures, matching the design's error-handling contract
