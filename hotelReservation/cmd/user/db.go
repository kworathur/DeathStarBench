package main

import (
	"context"
	"crypto/sha256"
	"fmt"
	"strconv"

	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

type User struct {
	Username string `bson:"username"`
	Password string `bson:"password"`
}

func initializeDatabase(url string) (*mongo.Client, func()) {
	log.Info().Msg("Generating test data...")

	newUsers := []interface{}{}

	for i := 0; i <= 500; i++ {
		suffix := strconv.Itoa(i)

		password := ""
		for j := 0; j < 10; j++ {
			password += suffix
		}
		sum := sha256.Sum256([]byte(password))

		newUsers = append(newUsers, User{
			fmt.Sprintf("Cornell_%x", suffix),
			fmt.Sprintf("%x", sum),
		})
	}

	uri := fmt.Sprintf("mongodb://%s", url)
	log.Info().Msgf("Attempting connection to %v", uri)

	opts := options.Client().ApplyURI(uri)
	client, err := mongo.Connect(context.TODO(), opts)
	if err != nil {
		log.Panic().Msg(err.Error())
	}
	log.Info().Msg("Successfully connected to MongoDB")

	collection := client.Database("user-db").Collection("user")
	count, err := collection.CountDocuments(context.TODO(), bson.D{})
	if err != nil {
		log.Panic().Msg(err.Error())
	}
	if count == 0 {
		_, err = collection.InsertMany(context.TODO(), newUsers)
		if err != nil {
			log.Fatal().Msg(err.Error())
		}
		log.Info().Msg("Successfully inserted test data into user DB")
	} else {
		log.Info().Msg("User DB already seeded, skipping insertion")
	}

	return client, func() {
		if err := client.Disconnect(context.TODO()); err != nil {
			log.Fatal().Msg(err.Error())
		}
	}
}
