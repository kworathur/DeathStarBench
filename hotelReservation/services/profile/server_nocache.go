//go:build no_memcache

package profile

import (
	"context"
	"sync"

	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile/proto"
)

// GetProfiles returns hotel profiles for requested IDs by querying MongoDB directly.
// No Memcached calls are made in this build variant.
func (s *Server) GetProfiles(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	log.Trace().Msgf("In GetProfiles (no_memcache build)")

	var wg sync.WaitGroup
	var mutex sync.Mutex
	var firstErr error

	res := new(pb.Result)
	hotels := make([]*pb.Hotel, 0)

	wg.Add(len(req.HotelIds))
	for _, hotelId := range req.HotelIds {
		go func(hotelId string) {
			defer wg.Done()

			var hotelProf *pb.Hotel

			collection := s.MongoClient.Database("profile-db").Collection("hotels")

			mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_profile")
			mongoSpan.SetTag("span.kind", "client")
			err := collection.FindOne(context.TODO(), bson.D{{"id", hotelId}}).Decode(&hotelProf)
			mongoSpan.Finish()

			if err != nil {
				log.Error().Msgf("Failed get hotels data: %v", err)
				mutex.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mutex.Unlock()
				return
			}

			mutex.Lock()
			hotels = append(hotels, hotelProf)
			mutex.Unlock()
		}(hotelId)
	}
	wg.Wait()

	if firstErr != nil {
		return nil, firstErr
	}

	res.Hotels = hotels
	log.Trace().Msgf("In GetProfiles after getting resp")
	return res, nil
}
