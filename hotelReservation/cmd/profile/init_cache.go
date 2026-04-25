//go:build !no_memcache

package main

import (
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/registry"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/tune"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/mongo"
)

func buildServer(result map[string]string, mongoClient *mongo.Client, tracer opentracing.Tracer, reg *registry.Client, servPort int, servIP string) *profile.Server {
	log.Info().Msgf("Read profile memcached address: %v", result["ProfileMemcAddress"])
	log.Info().Msg("Initializing Memcached client...")
	memcClient := tune.NewMemCClient2(result["ProfileMemcAddress"])
	log.Info().Msg("Success")

	return &profile.Server{
		Port:        servPort,
		IpAddr:      servIP,
		Tracer:      tracer,
		Registry:    reg,
		MongoClient: mongoClient,
		MemcClient:  memcClient,
	}
}
