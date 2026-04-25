# Requirements Document

## Introduction

The `hotelReservation` application uses Memcached as a caching layer in three backend services — **profile**, **rate**, and **reservation** — that are invoked as part of the hotel search flow triggered by `searchHandler`. This feature adds a Go build tag (`no_memcache`) that, when present at compile time, causes all three services to skip Memcached entirely and read/write directly from/to MongoDB. This is useful for benchmarking, testing, and deployments where Memcached is unavailable or undesirable.

## Glossary

- **Build_Tag**: A Go compile-time constraint declared with `//go:build <tag>` that selects which source files are compiled into the binary.
- **Profile_Service**: The `hotelReservation/services/profile` gRPC service, which caches hotel profile data in Memcached.
- **Rate_Service**: The `hotelReservation/services/rate` gRPC service, which caches hotel nightly rate data in Memcached.
- **Reservation_Service**: The `hotelReservation/services/reservation` gRPC service, which caches capacity and reservation counts in Memcached.
- **no_memcache**: The Go build tag that opts the binary out of all Memcached caching.
- **Cache_Path**: The code path that reads from and writes to Memcached before falling back to MongoDB.
- **Direct_Path**: The code path that reads from and writes to MongoDB without consulting Memcached.
- **MemcClient**: The `*memcache.Client` field on each service server struct, used to interact with Memcached.

## Requirements

### Requirement 1: Build Tag Declaration

**User Story:** As a developer, I want a single build tag to disable all Memcached caching, so that I can compile a no-cache binary without modifying source code.

#### Acceptance Criteria

1. THE Build_Tag `no_memcache` SHALL be a valid Go build constraint that can be passed to `go build` via `-tags no_memcache`.
2. WHEN the binary is compiled without the `no_memcache` tag, THE Profile_Service, Rate_Service, and Reservation_Service SHALL use the Cache_Path (existing behavior is preserved).
3. WHEN the binary is compiled with the `no_memcache` tag, THE Profile_Service, Rate_Service, and Reservation_Service SHALL use the Direct_Path for all data access.

---

### Requirement 2: Profile Service — No-Cache Path

**User Story:** As a developer, I want the Profile Service to bypass Memcached when built with `no_memcache`, so that hotel profiles are always fetched from MongoDB.

#### Acceptance Criteria

1. WHEN the `no_memcache` Build_Tag is set and `GetProfiles` is called, THE Profile_Service SHALL query MongoDB for every requested hotel ID without calling `MemcClient.GetMulti`.
2. WHEN the `no_memcache` Build_Tag is set and `GetProfiles` is called, THE Profile_Service SHALL return the same `*pb.Result` structure as the Cache_Path.
3. WHEN the `no_memcache` Build_Tag is set, THE Profile_Service SHALL NOT write fetched profiles back to Memcached.
4. IF the `no_memcache` Build_Tag is set and a MongoDB query fails, THEN THE Profile_Service SHALL log the error and return an error to the caller.

---

### Requirement 3: Rate Service — No-Cache Path

**User Story:** As a developer, I want the Rate Service to bypass Memcached when built with `no_memcache`, so that rate plans are always fetched from MongoDB.

#### Acceptance Criteria

1. WHEN the `no_memcache` Build_Tag is set and `GetRates` is called, THE Rate_Service SHALL query MongoDB for every requested hotel ID without calling `MemcClient.GetMulti`.
2. WHEN the `no_memcache` Build_Tag is set and `GetRates` is called, THE Rate_Service SHALL return the same sorted `*pb.Result` structure as the Cache_Path.
3. WHEN the `no_memcache` Build_Tag is set, THE Rate_Service SHALL NOT write fetched rate plans back to Memcached.
4. IF the `no_memcache` Build_Tag is set and a MongoDB query fails, THEN THE Rate_Service SHALL log the error and return an error to the caller.

---

### Requirement 4: Reservation Service — No-Cache Path

**User Story:** As a developer, I want the Reservation Service to bypass Memcached when built with `no_memcache`, so that availability checks and reservations always use MongoDB.

#### Acceptance Criteria

1. WHEN the `no_memcache` Build_Tag is set and `CheckAvailability` is called, THE Reservation_Service SHALL query MongoDB for capacity and reservation counts without calling any `MemcClient` methods.
2. WHEN the `no_memcache` Build_Tag is set and `MakeReservation` is called, THE Reservation_Service SHALL query MongoDB for capacity and reservation counts without calling any `MemcClient` methods.
3. WHEN the `no_memcache` Build_Tag is set and `MakeReservation` is called, THE Reservation_Service SHALL NOT write reservation counts or capacity values back to Memcached.
4. WHEN the `no_memcache` Build_Tag is set, THE Reservation_Service SHALL return the same result types and correctness guarantees as the Cache_Path.
5. IF the `no_memcache` Build_Tag is set and a MongoDB query fails, THEN THE Reservation_Service SHALL log the error and return an error to the caller.

---

### Requirement 5: MemcClient Initialization

**User Story:** As a developer, I want the services to start successfully without a Memcached address when built with `no_memcache`, so that I do not need to configure or run Memcached at all.

#### Acceptance Criteria

1. WHEN the `no_memcache` Build_Tag is set, THE Profile_Service, Rate_Service, and Reservation_Service SHALL start without initializing a `MemcClient` connection.
2. WHEN the `no_memcache` Build_Tag is set, THE Profile_Service, Rate_Service, and Reservation_Service SHALL NOT require a Memcached address in the configuration.
3. WHEN the `no_memcache` Build_Tag is NOT set, THE Profile_Service, Rate_Service, and Reservation_Service SHALL initialize `MemcClient` as before (existing behavior is preserved).

---

### Requirement 6: Build Correctness

**User Story:** As a developer, I want both the default and `no_memcache` builds to compile without errors, so that the build tag does not break the standard build.

#### Acceptance Criteria

1. THE binary compiled without the `no_memcache` tag SHALL compile successfully with `go build ./...` from the `hotelReservation` directory.
2. THE binary compiled with the `no_memcache` tag SHALL compile successfully with `go build -tags no_memcache ./...` from the `hotelReservation` directory.
3. WHEN both build variants are compiled, THE resulting binaries SHALL expose the same gRPC service interfaces and HTTP endpoints.
