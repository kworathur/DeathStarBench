//go:build no_memcache

package main

import (
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/registry"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile"
	"github.com/opentracing/opentracing-go"
	"go.mongodb.org/mongo-driver/mongo"
)

func buildServer(_ map[string]string, mongoClient *mongo.Client, tracer opentracing.Tracer, reg *registry.Client, servPort int, servIP string) *profile.Server {
	return &profile.Server{
		Port:        servPort,
		IpAddr:      servIP,
		Tracer:      tracer,
		Registry:    reg,
		MongoClient: mongoClient,
	}
}
