//go:build no_memcache

package profile

import (
	"context"
	"errors"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile/proto"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
)

var getProfileFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (*pb.Hotel, error) {
	collection := client.Database("profile-db").Collection("hotels")

	mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_profile")
	mongoSpan.SetTag("span.kind", "client")
	defer mongoSpan.Finish()

	hotelProf := new(pb.Hotel)
	if err := collection.FindOne(ctx, bson.D{{"id", hotelId}}).Decode(hotelProf); err != nil {
		return nil, err
	}
	return hotelProf, nil
}

// GetProfiles queries MongoDB directly for every requested hotel ID.
func (s *Server) GetProfiles(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	log.Trace().Msg("In GetProfiles")

	res := &pb.Result{Hotels: make([]*pb.Hotel, 0, len(req.HotelIds))}
	for _, hotelId := range req.HotelIds {
		hotelProf, err := getProfileFromMongo(ctx, s.MongoClient, hotelId)
		if errors.Is(err, mongo.ErrNoDocuments) {
			continue
		}
		if err != nil {
			log.Error().Msgf("Failed get hotels data for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}
		res.Hotels = append(res.Hotels, hotelProf)
	}

	log.Trace().Msg("In GetProfiles after getting resp")
	return res, nil
}
