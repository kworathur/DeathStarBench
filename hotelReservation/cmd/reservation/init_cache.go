//go:build !no_memcache

package main

import (
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/registry"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/reservation"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/tune"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/mongo"
)

func buildServer(result map[string]string, mongoClient *mongo.Client, tracer opentracing.Tracer, reg *registry.Client, servPort int, servIP string) *reservation.Server {
	log.Info().Msgf("Read reservation memcached address: %v", result["ReserveMemcAddress"])
	log.Info().Msg("Initializing Memcached client...")
	memcClient := tune.NewMemCClient2(result["ReserveMemcAddress"])
	log.Info().Msg("Success")

	return &reservation.Server{
		Tracer:      tracer,
		Registry:    reg,
		Port:        servPort,
		IpAddr:      servIP,
		MongoClient: mongoClient,
		MemcClient:  memcClient,
	}
}
