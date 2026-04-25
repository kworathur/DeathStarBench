//go:build no_memcache

package rate

import (
	"context"
	"sort"
	"sync"

	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/rate/proto"
)

// GetRates gets rates for hotels for specific date range by querying MongoDB directly.
// No Memcached calls are made in this build variant.
func (s *Server) GetRates(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := new(pb.Result)

	var wg sync.WaitGroup
	var mutex sync.Mutex
	var firstErr error

	ratePlans := make(RatePlans, 0)

	wg.Add(len(req.HotelIds))
	for _, hotelId := range req.HotelIds {
		go func(id string) {
			defer wg.Done()

			mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_rate")
			mongoSpan.SetTag("span.kind", "client")

			collection := s.MongoClient.Database("rate-db").Collection("inventory")
			filter := bson.D{
				{"hotelId", id},
				{"inDate", bson.D{{"$lte", req.InDate}}},
				{"outDate", bson.D{{"$gte", req.OutDate}}},
			}
			curr, err := collection.Find(context.TODO(), filter)
			mongoSpan.Finish()

			if err != nil {
				log.Error().Msgf("Failed to get rate data for hotel %s: %v", id, err)
				mutex.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mutex.Unlock()
				return
			}

			tmpRatePlans := make(RatePlans, 0)
			if curr != nil {
				if err := curr.All(context.TODO(), &tmpRatePlans); err != nil {
					log.Error().Msgf("Failed to decode rate data for hotel %s: %v", id, err)
					mutex.Lock()
					if firstErr == nil {
						firstErr = err
					}
					mutex.Unlock()
					return
				}
			}

			mutex.Lock()
			ratePlans = append(ratePlans, tmpRatePlans...)
			mutex.Unlock()
		}(hotelId)
	}
	wg.Wait()

	if firstErr != nil {
		return nil, firstErr
	}

	sort.Sort(ratePlans)
	res.RatePlans = ratePlans

	return res, nil
}
