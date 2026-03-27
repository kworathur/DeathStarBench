# DeathStarBench

Open-source benchmark suite for cloud microservices. DeathStarBench includes five end-to-end services, four for cloud systems, and one for cloud-edge systems running on drone swarms. 

## End-to-end Services <img src="microservices_bundle4.png" alt="suite-icon" width="40"/>

* Social Network (released)
* Media Service (released)
* Hotel Reservation (released)
* E-commerce site (in progress)
* Banking System (in progress)
* Drone coordination system (in progress)

## License & Copyright 

DeathStarBench is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.

DeathStarBench is being developed by the [SAIL group](http://sail.ece.cornell.edu/) at Cornell University. 

## Publications

More details on the applications and a characterization of their behavior can be found at ["An Open-Source Benchmark Suite for Microservices and Their Hardware-Software Implications for Cloud and Edge Systems"](http://www.csl.cornell.edu/~delimitrou/papers/2019.asplos.microservices.pdf), Y. Gan et al., ASPLOS 2019. 

If you use this benchmark suite in your work, we ask that you please cite the paper above. 


## Beta-testing

If you are interested in joining the beta-testing group for DeathStarBench, send us an email at: <microservices-bench-L@list.cornell.edu>

## Testing on Cloudlab

Pre-requisites

* A github public/private key pair
* Tested on Ubuntu 22.04.2 LTS

1. Clone project repository

```sh
git clone --recurse-submodules git@github.com:kworathur/DeathStarBench.git
```

2. Install all dependencies, compile wrk2, and build service binaries

```sh
cd DeathStarBench
chmod +x hotelReservation/scripts/install.sh
./hotelReservation/scripts/install.sh
```

This script installs wrk2 build dependencies, compiles LuaJIT, installs Go, builds all hotel reservation service binaries, and installs backing services (Consul, MongoDB, Memcached, Jaeger).
