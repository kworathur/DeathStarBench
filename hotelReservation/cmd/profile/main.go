package main

import (
	"flag"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/config"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/registry"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/tracing"
	"github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/tune"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	tune.Init()
	log.Logger = zerolog.New(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.RFC3339}).With().Timestamp().Caller().Logger()

	log.Info().Msg("Reading config...")
	result, configPath, err := config.LoadWithConfigFlag(os.Args[1:], "config.json")
	if err != nil {
		log.Fatal().Msgf("Got error while reading config: %v", err)
	}
	log.Info().Msgf("Loaded config from %s", *configPath)

	log.Info().Msg("Initializing DB connection...")
	mongoClient, mongoClose := initializeDatabase(result["ProfileMongoAddress"])
	defer mongoClose()

	log.Info().Msgf("Read profile memcashed address: %v", result["ProfileMemcAddress"])
	log.Info().Msg("Initializing Memcashed client...")
	memcClient := tune.NewMemCClient2(result["ProfileMemcAddress"])
	log.Info().Msg("Success")

	servPort, _ := strconv.Atoi(result["ProfilePort"])
	servIP := result["ProfileIP"]

	var (
		jaegerAddr = flag.String("jaegeraddr", result["jaegerAddress"], "Jaeger address")
		consulAddr = flag.String("consuladdr", result["consulAddress"], "Consul address")
	)
	flag.Parse()

	log.Info().Msgf("Initializing jaeger agent [service name: %v | host: %v]...", "profile", *jaegerAddr)
	tracer, err := tracing.Init("profile", *jaegerAddr)
	if err != nil {
		log.Panic().Msgf("Got error while initializing jaeger agent: %v", err)
	}
	log.Info().Msg("Jaeger agent initialized")

	log.Info().Msgf("Initializing consul agent [host: %v]...", *consulAddr)
	registry, err := registry.NewClient(*consulAddr)
	if err != nil {
		log.Panic().Msgf("Got error while initializing consul agent: %v", err)
	}
	log.Info().Msg("Consul agent initialized")

	srv := &profile.Server{
		Port:        servPort,
		IpAddr:      servIP,
		Tracer:      tracer,
		Registry:    registry,
		MongoClient: mongoClient,
		MemcClient:  memcClient,
	}

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-sigChan
		log.Info().Msg("Received shutdown signal, deregistering from Consul...")
		srv.Shutdown()
		os.Exit(0)
	}()

	log.Info().Msg("Starting server...")
	log.Fatal().Msg(srv.Run().Error())
}
