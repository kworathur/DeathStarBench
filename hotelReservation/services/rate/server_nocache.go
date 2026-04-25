//go:build no_memcache

package rate

import (
	"context"
	"sort"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/rate/proto"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
)

var getRatesFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (RatePlans, error) {
	collection := client.Database("rate-db").Collection("inventory")

	mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_rate")
	mongoSpan.SetTag("span.kind", "client")
	defer mongoSpan.Finish()

	curr, err := collection.Find(ctx, bson.D{{"hotelId", hotelId}})
	if err != nil {
		return nil, err
	}
	defer curr.Close(ctx)

	ratePlans := make(RatePlans, 0)
	if err := curr.All(ctx, &ratePlans); err != nil {
		return nil, err
	}
	return ratePlans, nil
}

// GetRates queries MongoDB directly and returns sorted rate plans.
func (s *Server) GetRates(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := new(pb.Result)
	ratePlans := make(RatePlans, 0)

	for _, hotelId := range req.HotelIds {
		tmpRatePlans, err := getRatesFromMongo(ctx, s.MongoClient, hotelId)
		if err != nil {
			log.Error().Msgf("Failed get rate data for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}
		ratePlans = append(ratePlans, tmpRatePlans...)
	}

	sort.Sort(ratePlans)
	res.RatePlans = []*pb.RatePlan(ratePlans)

	return res, nil
}
