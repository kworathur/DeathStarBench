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

2. Compile LuaJIT library from sources

```sh
sudo apt update
sudo apt-get install libssl-dev
sudo apt install zlib1g zlib1g-dev
sudo apt-get install luarocks 
cd DeathStarBench/wrk2 && make
```

3. Build server binaries for each microservice

```sh
sudo apt install golang-go
cd DeathStarBench/hotelReservation
go build -o bin/frontend ./cmd/frontend
go build -o bin/search ./cmd/search
go build -o bin/geo ./cmd/geo
go build -o bin/rate ./cmd/rate
go build -o bin/profile ./cmd/profile
go build -o bin/recommendation ./cmd/recommendation
go build -o bin/user ./cmd/user
go build -o bin/reservation ./cmd/reservation
go build -o bin/review ./cmd/review
go build -o bin/attractions ./cmd/attractions
```

4. Install project dependencies

Install consul
```sh
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install consul
```

Install mongodb 

```sh
sudo apt-get install gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg \
   --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl start mongod
```

Install memcached

```sh
sudo apt install memcached libmemcached-tools
sudo systemctl start memcached
sudo systemctl enable memcached
```

Install Jaeger (all-in-one)

```sh
wget https://github.com/jaegertracing/jaeger/releases/download/v2.16.0/jaeger-2.16.0-linux-amd64.tar.gz
tar -xzf jaeger-2.16.0-linux-amd64.tar.gz
sudo cp jaeger-2.16.0-linux-amd64/jaeger /usr/local/bin/
rm -rf jaeger-2.16.0-linux-amd64 jaeger-2.16.0-linux-amd64.tar.gz
```
