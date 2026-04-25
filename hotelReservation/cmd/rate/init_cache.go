//go:build !no_memcache

package main

import (
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/registry"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/rate"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/tune"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/mongo"
)

func buildServer(result map[string]string, mongoClient *mongo.Client, tracer opentracing.Tracer, reg *registry.Client, servPort int, servIP string) *rate.Server {
	log.Info().Msgf("Read rate memcached address: %v", result["RateMemcAddress"])
	log.Info().Msg("Initializing Memcached client...")
	memcClient := tune.NewMemCClient2(result["RateMemcAddress"])
	log.Info().Msg("Success")

	return &rate.Server{
		Tracer:      tracer,
		Registry:    reg,
		Port:        servPort,
		IpAddr:      servIP,
		MongoClient: mongoClient,
		MemcClient:  memcClient,
	}
}
