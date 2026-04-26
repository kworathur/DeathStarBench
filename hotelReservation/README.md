# Hotel Reservation

The application implements a hotel reservation service, build with Go and gRPC, and starting from the open-source project https://github.com/harlow/go-micro-services. The initial project is extended in several ways, including adding back-end in-memory and persistent databases, adding a recommender system for obtaining hotel recommendations, and adding the functionality to place a hotel reservation. 

<!-- ## Application Structure -->

<!-- ![Social Network Architecture](socialNet\_arch.png) -->

Supported actions:
* Get profile and rates of nearby hotels available during given time periods
* Recommend hotels based on user provided metrics
* Place reservations


## Reproducing the Progress Report Results

1. SSH into the client node and clone the repo 

```bash
git clone --recurse-submodules git@github.com:kworathur/DeathStarBench.git
```

2. Run the `install.sh` script (required for `wrk2`)
```bash
cd DeathStarBench/hotelReservation
./scripts/install.sh
```

3. SSH into the server node and clone the repo

```bash
git clone --recurse-submodules git@github.com:kworathur/DeathStarBench.git
```

4. Run the `install.sh` script
```bash
cd DeathStarBench/hotelReservation
./scripts/install.sh
```

5. Run the `start_backing.sh` script
```bash
./scripts/start_backing.sh
```

If successful, the script should output the URL of mongod, consul, and jaeger UI

6. Run the `start_services.sh` script
```bash
./scripts/start_services.sh
```

7. On the client node, run the testing script

```bash
python scripts/compare_schedutil_performance.py --ssh-user worathur --ssh-key ~/.ssh/id_rsa --server-host 10.10.1.1 --target hotels --remote-repo-root ~/DeathStarBench --threads 4 --conections 4 --rates 1000:10000:2000
```

8. The script will step through the QPS rates, generating poisson-distributed load with wrk2 and measuring power consumption for both `performance` and `schedutil` frequency governors.


## Running the Hotel Reservation Applications

### As Processes

To run the microservices as bare processes (no Docker), first follow the [installation instructions](../README.md).

1. Start backing services (Consul, MongoDB, Memcached, Jaeger):

```bash
./scripts/start\_backing.sh
```

2. Start all microservices:

```bash
./scripts/start\_services.sh
```

The script automatically picks up `config.local.json` if present. You can override with flags:

```bash
./scripts/start\_services.sh --config /path/to/config.json --consul 10.0.0.1:8500 --jaeger 10.0.0.2:6831
```

To start a single service (e.g. for the placement algorithm):

```bash
./scripts/start\_service.sh <service_name> [--config <path>] [--consul <addr>] [--jaeger <addr>]
```

3. Stop everything:

```bash
./scripts/stop\_all.sh
```

4. Verify the deployment:

```bash
# Check Consul registration
curl http://localhost:8500/v1/catalog/services

# Test the frontend
curl "http://localhost:5000/hotels?inDate=2015-04-09&outDate=2015-04-10&lat=38.0235&lon=-122.095"
```

Service logs are written to `/tmp/hotel-logs/`.

#### Running without Memcached (`no_memcache`)

`start_services.sh` runs whatever binaries are in `bin/`. To deploy without Memcached, rebuild the three affected services with the `no_memcache` tag before starting:

```bash
# Rebuild only the services that use Memcached
for svc in profile rate reservation; do
    go build -tags no_memcache -o "bin/$svc" "./cmd/$svc"
done
```

Then start as normal — Memcached does not need to be running:

```bash
./scripts/start_services.sh
```

To go back to the default (Memcached-enabled) build, rebuild without the tag:

```bash
for svc in profile rate reservation; do
    go build -o "bin/$svc" "./cmd/$svc"
done
```

### In Docker Containers

### Before you start
- Install Docker and Docker Compose.
- Make sure exposed ports in docker-compose files are available
- Consider which platform you want to use (docker-compose/openshift/kubernetes)
    - Build the required images using the proper method
        - In case of docker-compose => docker-compose build
        - In case of Openshift => run the build script according to the readme.
        - In case of kubernetes => run the build script according to the readme.

### Running the containers
##### Docker-compose
Start docker containers by running `docker compose up -d`. All images will be pulled from Docker Hub. In order to run `docker compose` with images built from the `Dockerfile`, run `docker compose up -d --build`.

The workload itself can be configured using optional enviroment variables. The available configuration items are:

- TLS: Environment variable TLS controls the TLS enablement of gRPC and HTTP communications of the microservices in hotelReservation.
    - TLS=0 or not set(default): No TLS enabled for gRPC and HTTP communication.
    - TLS=1: All the gRPC and HTTP communications will be protected by TLS, e.g. `TLS=1 docker compose up -d`.
    - TLS=<ciphersuite>: Use specified ciphersuite for TLS, e.g. `TLS=TLS\_ECDHE_RSA_WITH_AES_128_GCM_SHA256 docker- ompose up -d`. The avaialbe cipher suite can be found at the file [options.go](tls/options.go#L21).

- GC: Environment variable GC controls the garbage collection target percentage of Golang runtime. The default value is 100. See [golang doc](https://pkg.go.dev/runtime/debug#SetGCPercent) for details.

- JAEGER\_SAMPLE\_RATIO: Environment variable JAEGER\_SAMPLE\_RATIO controls the ratio of requests to be traced Jaeger. Default is 0.01(1%).

- MEMC\_TIMEOUT: Environment variable MEMC\_TIMEOUT controls the timeout value in seconds when communicating with memcached. Default is 2 seconds. We may need to increase this value in case of very high work loads.

- LOG\_LEVEL: Environment variable LOG\_LEVEL controls the log verbosity. Valid values are: ERROR, WARNING, INFO, TRACE, DEBUG. Default value is INFO.

Users may run `docker compose logs <service>` to check the corresponding configurations.

##### Openshift
Read the Readme file in Openshift directory.

##### Kubernetes
Read the Readme file in Kubernetes directory.

#### workload generation
Experiments are run on pairs of machines, with one machine acting as the client with generates load, while the other machine services HTTP requests
The distributed entrypoint is now a Python orchestrator, aligned with the remote setup flow used in `envoy-imbalancer-exp`:

- `scripts/power_sweep_remote_config.py` holds reusable node/auth defaults
- `scripts/power_sweep_remote_util.py` provides shared Paramiko helpers
- `scripts/run_distributed_power_sweeps.py` bootstraps remote checkouts and runs governor phases in parallel

Use `--refresh-repo` to `git fetch` and `git pull --ff-only` on existing remote checkouts before starting a new sweep.

../wrk2/wrk -D exp -t 4 -c 128 -d 300 -L -s ./wrk2/scripts/hotel-reservation/single-endpoint.lua http://c220g1-030808.wisc.cloudlab.us:5000 -R 10000 > schedutil_10000_hotels.txt

### Questions and contact

You are welcome to submit a pull request if you find a bug or have extended the application in an interesting way. For any questions please contact us at: <microservices-bench-L@list.cornell.edu>
